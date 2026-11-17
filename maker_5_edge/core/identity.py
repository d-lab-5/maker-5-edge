# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D-LAB-5
"""
identity.py — who this tool is, as far as the core needs to know.

Generated from .copier-answers.yml by the D-LAB-5 tool template. Change the
answer and run `copier update` rather than editing this file: it is core-owned,
and every other module under core/ reads its names from here so that those
modules come out byte-identical in every tool.
"""

TOOL_NAME = "maker-5-edge"
PACKAGE = "maker_5_edge"
TITLE = "Maker-5 Edge"
DESCRIPTION = "Local workstation and lab-bench edge for Maker-5: syncs Git repos, CAD/PCB artifacts and hardware telemetry with the cloud"
AUTHOR = "D-LAB-5"
COPYRIGHT = "© 2026 D-LAB-5"
LICENCE = "GPL-3.0-or-later"
LICENCE_URL = "https://www.gnu.org/licenses/gpl-3.0.html"
DISCLAIMER = ""
COFFEE_URL = "https://www.buymeacoffee.com/dlab5"

GITHUB_ORG = "d-lab-5"
REPO_NAME = "maker-5-edge"
REPO_URL = f"https://github.com/{GITHUB_ORG}/{REPO_NAME}"
DEFAULT_BRANCH = "main"

DEFAULT_PORT = 8773

# The template this tool was generated from, and the version last applied to
# it — the same value as _commit in .copier-answers.yml, which lives at the
# repository root and is not shipped with an installed copy, so it is written
# here too. A tag like "v0.4.0" is a published template release; anything with
# a commit suffix ("v0.4.0-2-g1a2b3c4") was rendered from an unreleased commit.
TEMPLATE_NAME = "python-tool-template"
TEMPLATE_URL = "https://github.com/ERP-LAB-5/python-tool-template"
TEMPLATE_VERSION = "v0.4.1"

CLI_COMMAND = "maker-5-edge"
CLI_MODULE = "engine"
WEB_COMMAND = "maker-5-edge-web"
MCP_COMMAND = "maker-5-edge-mcp"
SKILL_COMMAND = "maker-5-edge-skill"
SKILL_NAME = "maker-5-edge"

WITH_MCP = True
WITH_WORKSPACE = True
WITH_PLUGIN = True
WORKSPACE_DIR = "mydocs"
SHARED_DIR = "shared"
