# NVDA settings integration (GPLv2).
# Registers Bitgil's config spec and a settings panel so users configure the
# provider, API key, model, and narration density without editing files.
#
# All imports here are NVDA-runtime modules (config, gui, wx); this module is
# only imported inside the NVDA process, never by the core or the test suite.

from __future__ import annotations

import config
import gui
import wx
from gui.settingsDialogs import SettingsPanel

CONFIG_SECTION = "bitgil"

# configobj validation spec. API key stays in NVDA's config (user-local); it is
# never logged and never committed — see SECURITY.md.
CONFIG_SPEC = {
	"provider": 'string(default="ollama")',   # ollama | anthropic | openai
	"apiKey": 'string(default="")',            # BYO API Key (blank for local Ollama)
	"model": 'string(default="")',             # blank → provider default
	"profile": 'string(default="general")',    # active profile pack
	"density": 'string(default="profile")',     # profile | brief | normal | detailed
}

_PROVIDERS = ["ollama", "anthropic", "openai"]
# "profile" means: inherit the density set in the profile pack (don't override).
_DENSITIES = ["profile", "brief", "normal", "detailed"]


def initialize() -> None:
	"""Install the config spec. Call once from the plugin constructor."""
	config.conf.spec[CONFIG_SECTION] = CONFIG_SPEC


def get_config():
	return config.conf[CONFIG_SECTION]


class BitgilSettingsPanel(SettingsPanel):
	title = "Bitgil (빛길)"

	def makeSettings(self, settingsSizer):
		helper = gui.guiHelper.BoxSizerHelper(self, sizer=settingsSizer)
		conf = get_config()

		self._provider = helper.addLabeledControl(
			"프로바이더 (Provider)", wx.Choice, choices=_PROVIDERS
		)
		self._provider.SetStringSelection(conf["provider"])

		self._apiKey = helper.addLabeledControl(
			"API 키 (BYO API Key)", wx.TextCtrl, style=wx.TE_PASSWORD
		)
		self._apiKey.SetValue(conf["apiKey"])

		self._model = helper.addLabeledControl("모델 (빈칸=기본값)", wx.TextCtrl)
		self._model.SetValue(conf["model"])

		from .profiles import available_profile_names

		names = available_profile_names()
		self._profile = helper.addLabeledControl(
			"프로파일 (Profile)", wx.Choice, choices=names
		)
		if conf["profile"] in names:
			self._profile.SetStringSelection(conf["profile"])
		elif names:
			self._profile.SetSelection(0)

		self._density = helper.addLabeledControl(
			"해설 밀도 (Density)", wx.Choice, choices=_DENSITIES
		)
		self._density.SetStringSelection(conf["density"])

	def onSave(self):
		conf = get_config()
		conf["provider"] = self._provider.GetStringSelection()
		conf["apiKey"] = self._apiKey.GetValue()
		conf["model"] = self._model.GetValue()
		conf["profile"] = self._profile.GetStringSelection()
		conf["density"] = self._density.GetStringSelection()


def register_panel() -> None:
	gui.settingsDialogs.NVDASettingsDialog.categoryClasses.append(BitgilSettingsPanel)


def unregister_panel() -> None:
	try:
		gui.settingsDialogs.NVDASettingsDialog.categoryClasses.remove(BitgilSettingsPanel)
	except ValueError:
		pass
