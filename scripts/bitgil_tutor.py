#!/usr/bin/env python3
"""Bitgil 과외 모드 CLI — 시험지 PDF를 함께 읽는 대화 루프(문서 직독).

화면 캡처 데모(`bitgil_demo.py`)와 나란한 두 번째 입력 경로입니다. 지문·선택지는 PDF
텍스트 레이어에서 그대로 읽고(모델을 거치지 않음), 도표만 비전 모델에 넘기고, 모델이 말한
숫자는 원문과 대조합니다. 설계 근거는 `core/bitgil_core/tutor.py` 문서 문자열 참고.

사용 예:
  # 키 없이 (프로바이더 = demo, 캔에 담긴 문장이지만 흐름 확인용)
  python scripts/bitgil_tutor.py --pdf 모의고사.pdf

  # 실제 모델로 대화하며
  python scripts/bitgil_tutor.py --pdf 모의고사.pdf --provider bedrock --profile learning-chart

  # 한 번만 물어보고 끝내기(스크립트·테스트용)
  python scripts/bitgil_tutor.py --pdf 모의고사.pdf --ask "3번 읽어줘"
"""

from __future__ import annotations

import argparse
import os
import sys
import time

# Allow running from a checkout without installing bitgil-core.
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "core"))

from bitgil_core.document import load_pdf  # noqa: E402
from bitgil_core.engine import NarrationEngine  # noqa: E402
from bitgil_core.profiles import Profile, load_builtin_profiles  # noqa: E402
from bitgil_core.providers import build_provider  # noqa: E402
from bitgil_core.review import ReviewLog  # noqa: E402
from bitgil_core.tutor import TutorSession  # noqa: E402

DEFAULT_PROFILES_DIR = os.path.join(_REPO, "profiles")

_HELP = """말하거나 입력할 수 있는 것:
  3번            그 문항의 지문과 선택지를 원문 그대로 읽습니다(모델 안 씀)
  선택지          지금 문항의 선택지만 다시
  다음 / 이전     문항 이동          다시  직전 응답 반복
  도표 설명해줘    페이지 그림을 비전 모델로 설명 + 원문에 없는 숫자 고지
  2쪽 도표        쪽을 지정해서 설명
  (그 밖의 말)    문항 원문을 근거로 답합니다
  몇 문제         문서 개요        나가기 / quit  종료"""


def _load_profile(name: str, directory: str) -> Profile:
	if os.path.isdir(directory):
		packs = load_builtin_profiles(directory)
		if name in packs:
			return packs[name]
	if name == "general":
		return Profile(name="general", system_prompt="화면을 간결히 설명하세요.")
	sys.exit(f"error: profile '{name}' not found in {directory}")


def _print(reply, elapsed: float | None = None) -> None:
	"""응답 한 건을 출력. 원문 낭독인지 모델 답인지 **매번** 밝힙니다.

	같은 목소리로 읽히는 두 종류의 문장을 사용자가 구분할 수 있어야 하기 때문입니다 —
	하나는 시험지 원문이고, 하나는 모델의 말입니다. 복습 노트의 기계생성 고지와 같은 이유.
	"""
	tag = "원문" if reply.grounded else "모델"
	timing = f" {elapsed:.1f}초" if elapsed is not None else ""
	print(f"\n[{tag}{timing}] {reply.text}")
	if reply.unsupported:
		print(f"  ↳ 원문 미확인 숫자: {', '.join(reply.unsupported)}")


def main() -> None:
	p = argparse.ArgumentParser(description="Bitgil tutor mode (PDF direct read)")
	p.add_argument("--pdf", required=True, help="시험지 PDF 경로")
	p.add_argument("--provider", default="demo",
	               help="demo (키 없음) | bedrock | omniroute | anthropic | openai | gemini")
	p.add_argument("--model", help="프로바이더 기본 모델 대신 쓸 모델 id")
	p.add_argument("--api-key", help="API 키 (없으면 프로바이더의 환경변수에서 읽음)")
	p.add_argument("--base-url", help="프로바이더 엔드포인트 (ollama / omniroute)")
	p.add_argument("--profile", default="learning-chart", help="프로파일 팩 이름")
	p.add_argument("--profiles-dir", default=DEFAULT_PROFILES_DIR)
	p.add_argument("--ask", action="append", default=[],
	               help="한 번만 물어보고 종료 (여러 번 지정하면 순서대로 실행)")
	p.add_argument("--dpi", type=int, default=150, help="도표 렌더링 해상도")
	p.add_argument("--review", help="복습 노트를 이 경로에 markdown으로 저장")
	args = p.parse_args()

	try:
		document = load_pdf(args.pdf)
	except (FileNotFoundError, ValueError, RuntimeError) as exc:
		sys.exit(f"{exc}")

	profile = _load_profile(args.profile, args.profiles_dir)
	provider_config = {}
	if args.api_key:
		provider_config["api_key"] = args.api_key
	if args.model:
		provider_config["model"] = args.model
	if args.base_url:
		provider_config["base_url"] = args.base_url
	provider = build_provider(args.provider, provider_config, speed=profile.speed)

	model = getattr(provider, "model", "?")
	review = ReviewLog(
		clock=lambda: time.strftime("%H:%M:%S"), provider=provider.name, model=model
	)
	# 노트는 세션만 적습니다 — 엔진에도 주면 도표 설명이 두 번 남습니다(엔진의 원본 +
	# 세션의 고지 붙은 문장). 남겨야 하는 쪽은 고지가 붙은 문장입니다.
	engine = NarrationEngine(provider, profile)
	session = TutorSession(document, engine, review_log=review, render_dpi=args.dpi)

	# 쪽수·문항 수는 개요가 낭독으로 말해 줍니다 — 여기서 되풀이하면 같은 정보를 두 번 듣습니다.
	# 이 줄에는 낭독 대상이 아닌 것(어떤 프로바이더/모델을 쓰는지)만 남깁니다.
	print(
		f"[{os.path.basename(args.pdf)} | profile={profile.name} "
		f"provider={provider.name} model={model}]"
	)
	_print(session.overview())

	try:
		if args.ask:
			for utterance in args.ask:
				print(f"\n> {utterance}")
				started = time.monotonic()
				_print(session.respond(utterance), time.monotonic() - started)
		else:
			print(f"\n{_HELP}")
			_repl(session)
	except (KeyboardInterrupt, EOFError):
		print()
	finally:
		if args.review:
			with open(args.review, "w", encoding="utf-8") as f:
				f.write(review.to_markdown())
			print(f"\n복습 노트를 {args.review}에 저장했습니다.")


def _repl(session: TutorSession) -> None:
	while True:
		try:
			line = input("\n> ").strip()
		except (KeyboardInterrupt, EOFError):
			print()
			return
		if line in ("나가기", "종료", "quit", "exit", "q"):
			return
		if line in ("도움", "도움말", "help", "?"):
			print(_HELP)
			continue
		started = time.monotonic()
		try:
			_print(session.respond(line), time.monotonic() - started)
		except Exception as exc:
			# 낭독 대상이 사용자다 — 예외를 그대로 던지지 않고 무엇을 하면 되는지 말합니다.
			print(f"\n[오류] {exc}")


if __name__ == "__main__":
	main()
