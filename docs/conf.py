# Configuration file for the Sphinx documentation builder.
#
# This file only contains a selection of the most common options. For a full
# list see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Path setup --------------------------------------------------------------

# If extensions (or modules to document with autodoc) are in another directory,
# add these directories to sys.path here. If the directory is relative to the
# documentation root, use os.path.abspath to make it absolute, like shown here.
#
import os
import sys
import re

sys.path.insert(0, os.path.abspath("."))
sys.path.insert(0, os.path.abspath(".."))
sys.path.insert(1, os.path.abspath("../RNAmediator"))
from RNAmediator import _version

__version__ = _version.get_versions()["version"]


# -- Project information -----------------------------------------------------

project = "RNAmediator"
copyright = "2021, Joerg Fallmann"
author = "Joerg Fallmann"

# The full version, including alpha/beta/rc tags
release = __version__

# -- General configuration ---------------------------------------------------
# Master file to be generated

master_doc = "index"

# Add any Sphinx extension module names here, as strings. They can be
# extensions coming with Sphinx (named 'sphinx.ext.*') or your custom
# ones.
extensions = [
    "sphinx.ext.napoleon",
    "sphinx.ext.autodoc",
    "sphinx.ext.doctest",
    "sphinx.ext.mathjax",
    "sphinx.ext.autosummary",
    'sphinx.ext.intersphinx',
    "recommonmark",
    "sphinx_rtd_theme",
]

autosummary_generate = True
# Add any paths that contain templates here, relative to this directory.
templates_path = ["source/_templates"]

# List of patterns, relative to source directory, that match files and
# directories to ignore when looking for source files.
# This pattern also affects html_static_path and html_extra_path.
exclude_patterns = []


# -- Options for HTML output -------------------------------------------------

# The theme to use for HTML and HTML Help pages.  See the documentation for
# a list of builtin themes.
#
# html_theme = 'classic'
html_theme = "sphinx_rtd_theme"

html_theme_options = {
    # Toc options
    "collapse_navigation": True,
    "sticky_navigation": True,
    "navigation_depth": 4,
    "includehidden": True,
    "titles_only": False,
}

# Add any paths that contain custom static files (such as style sheets) here,
# relative to this directory. They are copied after the builtin static files,
# so a file named "default.css" will overwrite the builtin "default.css".
html_static_path = ["html/_static"]
pygments_style = "sphinx"
autosummary_mock_imports = [
    'RNAmediator.conftest',
]

def autodoc_skip_member_handler(app, what, name, obj, skip, options):
    # Basic approach; you might want a regex instead#
    pattern = re.compile(".{0,}test.{0,}")
    return bool(pattern.match(name))

# Automatically called by sphinx at startup
def setup(app):
    # Connect the autodoc-skip-member event from apidoc to the callback
    app.connect('autodoc-skip-member', autodoc_skip_member_handler)