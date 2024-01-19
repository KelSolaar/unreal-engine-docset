Unreal Engine Docset
====================

A `Python <https://www.python.org>`__ module defining objects to generate a
`Dash <https://kapeli.com/dash>`__ compatible docset from
`Unreal Engine documentation <https://docs.unrealengine.com>`__.

It is open source and freely available under the
`BSD-3-Clause <https://opensource.org/licenses/BSD-3-Clause>`__ terms.

..  image:: https://raw.githubusercontent.com/KelSolaar/unreal-engine-docset/main/docs/_static/UnrealEngineC++APILandingPage.png

.. contents:: **Table of Contents**
    :backlinks: none
    :depth: 2

.. sectnum::

Features
--------

The following **Unreal Engine** docsets are currently supported:

-   C++ API
-   Blueprint API
-   Python API

User Guide
----------

Installation
^^^^^^^^^^^^

Poetry
~~~~~~

The *OpenColorIO Configuration for ACES* repository adopts `Poetry <https://poetry.eustace.io>`__
to help managing its dependencies, this is the recommended way to get started
with development.

Assuming `python >= 3.10 <https://www.python.org/download/releases>`__ is
available on your system the development dependencies are installed with
`Poetry <https://poetry.eustace.io>`__ as follows:

.. code-block:: shell

    git clone https://github.com/KelSolaar/unreal-engine-docset.git
    cd unreal-engine-docset
    poetry install

Usage
^^^^^

The module expects a **Unreal Engine** *tgz* file as an input, they are
typically found in the ``Engine/Documentation/Builds`` directory, e.g.
``Engine/Documentation/Builds/CppAPI-HTML.tgz``, and an output directory:

.. code-block:: shell

    python unreal_engine_docset.py --input "/Users/Shared/Epic Games/UE_5.3/Engine/Documentation/Builds/BlueprintAPI-HTML.tgz" --output "/Users/Shared/Epic Games/UE_5.3/Engine/Documentation/Builds"

About
-----

| **Unreal Engine Docset** by Thomas Mansencal
| Copyright 2024 Thomas Mansencal – `thomas.mansencal@gmail.com <mailto:thomas.mansencal@gmail.com>`__
| This software is released under terms of BSD-3-Clause: https://opensource.org/licenses/BSD-3-Clause
| `https://github.com/KelSolaar/unreal-engine-docset.git <https://github.com/KelSolaar/unreal-engine-docset.git>`__
