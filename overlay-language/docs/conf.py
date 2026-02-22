# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

import sys
from pathlib import Path

from sphinx_github_style.utils.git import get_head

# -- Path setup --------------------------------------------------------------
# Add overlay-language/src to sys.path so autodoc can import the modules.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = 'Overlay Language'
copyright = '2025, Bo Yang'
author = 'Bo Yang'

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.extlinks',
    'sphinx_github_style',
    'sphinx_mdinclude',
]

source_suffix = {
    '.rst': 'restructuredtext',
    '.md': 'markdown',
}

autodoc_default_options = {
    'imported-members': True,
}

templates_path = ['_templates']
exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store', 'api/modules.rst', 'api/overlay.rst']



# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = 'alabaster'
html_theme_options = {
    'fixed_sidebar': True,
    'github_user': 'Atry',
    'github_repo': 'overlay',
    'github_button': True,
    'github_type': 'watch',
    'github_count': True,
}

# -- GitHub source links (pinned to git commit) --------------------------------

linkcode_blob = "head"
linkcode_url = "https://github.com/Atry/overlay"

_git_blob = get_head()

extlinks = {
    'github': (
        f'https://github.com/Atry/overlay/tree/{_git_blob}/%s',
        '%s',
    ),
}
