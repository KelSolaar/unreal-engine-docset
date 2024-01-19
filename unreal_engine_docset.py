"""
Unreal Engine Docset
====================

Defines the objects to generate a `Dash <https://kapeli.com/dash>`__ compatible
docset from `Unreal Engine documentation <https://docs.unrealengine.com>`__:

-   :func:`generate_docset`
"""

from __future__ import annotations

import html
import logging
import multiprocessing
import os
import re
import sqlite3
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from itertools import chain
from pathlib import Path
from typing import Callable, List, Tuple, cast
from xml.dom import minidom

import click
import lxml.html
import setuptools.archive_util
from lxml import etree  # pyright: ignore
from lxml.html import fromstring, tostring
from tqdm.contrib.concurrent import process_map

__author__ = "Thomas Mansencal"
__copyright__ = "Copyright 2024 Thomas Mansencal"
__license__ = "BSD-3-Clause - https://opensource.org/licenses/BSD-3-Clause"
__maintainer__ = "Thomas Mansencal"
__email__ = "thomas.mansencal@gmail.com"
__status__ = "Production"

__all__ = [
    "Collector",
    "ApiInformation",
    "Entry",
    "MAPPING_API_TYPE_TO_ENTRY_TYPE",
    "chdir",
    "join_path",
    "read_xml_file",
    "collector_cpp_default",
    "collector_cpp_nohref",
    "COLLECTORS_CPP",
    "collector_blueprint_default",
    "COLLECTORS_BLUEPRINT",
    "collect_api_name_and_syntax",
    "collect_api_information",
    "process_cpp_html_file",
    "process_cpp_docset",
    "process_blueprint_html_file",
    "process_blueprint_docset",
    "generate_database",
    "generate_plist",
    "generate_docset",
]

logger = logging.getLogger(__name__)


@dataclass
class Collector:
    """
    Define a collector selecting data from *Unreal Engine* documentation.

    Parameters
    ----------
    type
         Entry type corresponding to a supported *Dash*
        `entry type <https://kapeli.com/docsets#supportedentrytypes>`__.
    xpath
        *XPath* expression to collect the data.
    processor
        Callable processing the collected data.
    """

    type: str
    xpath: str
    processor: Callable


@dataclass(frozen=True)
class ApiInformation:
    """
    Define the *API* information for an *Unreal Engine* object and *Dash*
    documentation.

    Parameters
    ----------
    name
        Object *API* name.
    ue_type
        *Unreal Engine* object *API* type, e.g. ``UCLASS``.
    dash_type
        *Dash* documentation entry type, e.g. ``Class``.
    """

    name: str | None
    ue_type: str | None
    dash_type: str | None


@dataclass(frozen=True)
class Entry:
    """
    Define a *Dash* documentation entry.

    Parameters
    ----------
    name
        Object name.
    path
        Object path in the documentation, typically a relative html path.
    type
        *Dash* entry type, e.g. ``Class``.
    """

    name: str
    path: str
    type: str


MAPPING_API_TYPE_TO_ENTRY_TYPE: dict = {
    "class": "Class",
    "UCLASS": "Class",
    "struct": "Struct",
    "USTRUCT": "Struct",
    "union": "Union",
}
"""Mapping of *Unreal Engine* *API* type to *Dash* entry type."""


class chdir:
    """
    Define a context manager to change the current working directory.

    Parameters
    ----------
    path
        Desired working directory.
    """

    def __init__(self, path: Path | str):
        self.path = path
        self._old_cwd = []

    def __enter__(self):
        self._old_cwd.append(os.getcwd())
        os.chdir(self.path)

    def __exit__(self, *excinfo):
        os.chdir(self._old_cwd.pop())


def join_path(parent: Path | str, name: str) -> str:
    """
    Join given parent and name into a path.

    Parameters
    ----------
    parent
        Parent to join.
    name
        Name to join.

    Returns
    -------
    :class:`str`
        Joined path.
    """

    parent = re.sub(r"\\?/?index.html$", "", str(parent))

    return f"{parent}/{name}"


def read_xml_file(xml_path: Path | str, attempts: int = 10) -> lxml.html.HtmlElement:
    """
    Attempt to read given *XML* file.

    Because of multiprocessing, it seems like on *macOS*, files might be
    accessed concurrently causing *XML* parsing failure.

    Parameters
    ----------
    xml_path
        Path of the *XML* file to read.
    attempts
        Number of attempts to try to read the file. One is usually required.

    Returns
    -------
    :class:`lxml.html.HtmlElement`
        *XML* element.
    """

    i = 0
    while i < attempts:
        try:
            with open(xml_path, "r") as xml_file:
                xml = xml_file.read()

            return fromstring(xml.encode("utf-8"))
        except etree.ParserError:
            logger.debug(
                'Could not parse "%s" file on attempt %s, sleeping...', xml_path, i + 1
            )
            i += 1
            time.sleep(0.1)
            continue

    raise RuntimeError('Could not parse "%s" file!', xml_path)


def collector_cpp_default(
    elements: List[lxml.html.HtmlElement],
    parent_api_information: ApiInformation,
    html_path: Path,
) -> List[Tuple[str, str]]:
    """
    Collect the *C++* *API* data for given elements.

    This is the default collector.

    Parameters
    ----------
    elements
        Elements to collect the data from.
    parent_api_information
        Parent *Unreal Engine* object and *Dash* documentation *API*
        information.
    html_path
        Path of the file the elements are contained into.

    Returns
    -------
    :class:`list`
        Collected data.
    """

    collection = []
    for element in elements:
        collected_path = join_path(html_path, element.attrib["href"])

        if not Path(collected_path).exists():
            continue

        collected_name = collect_api_information(read_xml_file(collected_path)).name

        collection.append((collected_name, collected_path))

    return collection


def collector_cpp_nohref(
    elements: List[lxml.html.HtmlElement],
    parent_api_information: ApiInformation,
    html_path: Path,
) -> List[Tuple[str, str]]:
    """
    Collect the *C++* *API* data for given elements without an ``href``.

    Parameters
    ----------
    elements
        Elements to collect the data from.
    parent_api_information
        Parent *Unreal Engine* object and *Dash* documentation *API*
        information.
    html_path
        Path of the file the elements are contained into.

    Returns
    -------
    :class:`list`
        Collected data.
    """

    collection = []
    for element in elements:
        name = element.text_content()
        if parent_api_information.ue_type is not None:
            name = f"{parent_api_information.name}.{name}"

        collection.append((name, f"{html_path}#{name}"))

    return collection


COLLECTORS_CPP: Tuple[Collector, ...] = (
    Collector(
        "Module",
        './/div[@class="modules-list"]//td[@class="name-cell"]/a[not(@class="dashAnchor")]',
        collector_cpp_default,
    ),
    Collector(
        "Class",
        './/div[@id="classes"]//td[@class="name-cell"][1]/a[not(@class="dashAnchor")]',
        collector_cpp_default,
    ),
    Collector(
        "Constructor",
        './/div[@id="constructor"]//td[@class="name-cell"][1]/a[not(@class="dashAnchor")]',
        collector_cpp_default,
    ),
    Collector(
        "Destructor",
        './/div[@id="destructor"]//td[@class="name-cell"][1]/a[not(@class="dashAnchor")]',
        collector_cpp_default,
    ),
    Collector(
        "Type",
        './/div[@id="typedefs"]//td[@class="name-cell"][1]/a[not(@class="dashAnchor")]',
        collector_cpp_default,
    ),
    Collector(
        "Enum",
        './/div[@id="enums"]//td[@class="name-cell"][1]/a[not(@class="dashAnchor")]',
        collector_cpp_default,
    ),
    Collector(
        "Variable",
        './/div[@id="variables"]//td[@class="name-cell"][2]/a[not(@class="dashAnchor")]',
        collector_cpp_default,
    ),
    Collector(
        "Variable",
        './/div[@id="deprecatedvariables"]//td[@class="name-cell"][2]/a[not(@class="dashAnchor")]',
        collector_cpp_default,
    ),
    Collector(
        "Variable",
        './/div[@id="variables"]//td[@class="name-cell"][2]/p',
        collector_cpp_nohref,
    ),
    Collector(
        "Variable",
        './/div[@id="deprecatedvariables"]//td[@class="name-cell"][2]/p',
        collector_cpp_nohref,
    ),
    Collector(
        "Constant",
        './/div[@id="constants"]//td[@class="name-cell"][1]/a[not(@class="dashAnchor")]',
        collector_cpp_default,
    ),
    Collector(
        "Function",
        './/div[starts-with(@id, "functions_")]//td[@class="name-cell"][2]/a[not(@class="dashAnchor")]',
        collector_cpp_default,
    ),
    Collector(
        "Function",
        './/div[starts-with(@id, "deprecatedfunctions")]//td[@class="name-cell"][2]/a[not(@class="dashAnchor")]',
        collector_cpp_default,
    ),
)
"""*Unreal Engine* documentation collectors for *C++*."""


def collector_blueprint_default(
    elements: List[lxml.html.HtmlElement],
    parent_api_information: ApiInformation,
    html_path: Path,
) -> List[Tuple[str, str]]:
    """
    Collect the *Blueprint++* *API* data for given elements.

    This is the default collector.

    Parameters
    ----------
    elements
        Elements to collect the data from.
    parent_api_information
        Parent *Unreal Engine* object and *Dash* documentation *API*
        information.
    html_path
        Path of the file the elements are contained into.

    Returns
    -------
    :class:`list`
        Collected data.
    """

    collection = []
    for element in elements:
        collected_path = join_path(html_path, element.attrib["href"])

        if not Path(collected_path).exists():
            continue

        collected_name = collect_api_information(read_xml_file(collected_path)).name

        collection.append(
            (f"{parent_api_information.name}.{collected_name}", collected_path)
        )

    return collection


COLLECTORS_BLUEPRINT: Tuple[Collector, ...] = (
    Collector(
        "Function",
        './/h2[@id="actions"]/following-sibling::div[@class="member-list"]//td[@class="name-cell"]/a[not(@class="dashAnchor")]',
        collector_blueprint_default,
    ),
    Collector(
        "Category",
        './/h2[@id="categories"]/following-sibling::div[@class="member-list"]//td[@class="name-cell"]/a[not(@class="dashAnchor")]',
        collector_blueprint_default,
    ),
)
"""*Unreal Engine* documentation collectors for *Blueprint*."""


def collect_api_name_and_syntax(
    xml: lxml.html.HtmlElement,
) -> Tuple[str, str]:
    """
    Collect the *API* name and syntax from given *XML* element.

    Parameters
    ----------
    xml
        *XML* element to collect the *API* name and syntax from.

    Returns
    -------
    :class:`tuple`
        Collected *API* name and syntax.
    """

    title = next(iter(xml.xpath('.//h1[@id="H1TitleId"]/text()')))

    syntax = "\n".join(
        element.text_content()
        for element in xml.xpath('.//div[@class="simplecode_api"]/p')
    )

    return title, syntax


def collect_api_information(
    xml: lxml.html.HtmlElement,
) -> ApiInformation:
    """
    Collect the *API* information from given *XML* element.

    Parameters
    ----------
    xml
        *XML* element to collect the *API* information from.

    Returns
    -------
    :class:`ApiInformation`
        Collected *API* information.
    """

    api_name, api_syntax = collect_api_name_and_syntax(xml)
    for api_type, entry_type in MAPPING_API_TYPE_TO_ENTRY_TYPE.items():
        try:
            search = re.search(f"{api_type} {api_name}", api_syntax, re.MULTILINE)
        except re.error:
            continue

        if search is not None:
            return ApiInformation(api_name, api_type, entry_type)

    return ApiInformation(api_name, "object", "Object")


def process_cpp_html_file(
    html_path: Path,
    collectors: Tuple = COLLECTORS_CPP,
    add_dash_anchors: bool = True,
) -> List[Entry]:
    """
    Process given *Unreal Engine* *C++* *HTML* file using given collectors.

    Parameters
    ----------
    html_path
         *HTML* file path to collect the data from.
    collectors
        Collectors used to process the *HTML* file.
    add_dash_anchors
        Whether to add *Dash* anchors to generate a
        `TOC <https://kapeli.com/docsets#tableofcontents>`__.

    Returns
    -------
    :class:`list`
        List of *Dash* documentation entries.
    """

    logger.info('Processing "%s" file...', html_path)

    def localiser(link):
        """Update given link to point to an actual *HTML* file"""

        index_path = html_path.parent / Path(link) / "index.html"

        if not index_path.exists():
            return link

        return f"{link}/index.html"

    xml = read_xml_file(html_path)
    xml.rewrite_links(localiser)

    api_information = collect_api_information(xml)

    has_dash_anchors = len(xml.xpath('.//a[@class="dashAnchor"]')) != 0

    entries = []
    for collector in collectors:
        elements = xml.xpath(collector.xpath)
        anchors = []
        for i, collection in enumerate(
            collector.processor(elements, api_information, html_path)
        ):
            print(collection)
            collected_name, collected_html_path = collection

            if not Path(collected_html_path).exists():
                continue

            collected_type = collector.type

            # "class", "UCLASS", "struct", "USTRUCT" and "union" are classified
            # as "classes", we are providing more granularity.
            if collector.type == "Class":
                collected_xml = read_xml_file(collected_html_path)
                collected_api_information = collect_api_information(collected_xml)
                collected_type = collected_api_information.dash_type

            if add_dash_anchors and not has_dash_anchors:
                anchor_element = etree.Element("a")
                anchor_element.set("class", "dashAnchor")
                anchor_name = collected_name.split("::")[-1]

                suffix = ""
                if anchor_name in anchors:
                    count = anchors.count(anchor_name)
                    suffix = f" (Overload {count})"

                anchors.append(anchor_name)

                anchor_name = f"{anchor_name}{suffix}"

                anchor_element.set(
                    "name",
                    f"//apple_ref/cpp/{collected_type}/{html.escape(anchor_name)}",
                )
                elements[i].addprevious(anchor_element)

            entries.append(
                Entry(
                    cast(str, collected_name),
                    cast(str, collected_html_path),
                    cast(str, collected_type),
                )
            )

    with open(html_path, "w") as html_file:
        html_file.write(tostring(xml).decode("utf-8"))  # pyright: ignore

    return entries


def process_cpp_docset(api_directory: Path) -> set[Entry]:
    """
    Process given *Unreal Engine* *C++* docset.

    Parameters
    ----------
    api_directory
         Docset *API* path, e.g.``en-US/API``.

    Returns
    -------
    :class:`set`
        Set of entries.
    """

    logger.info("Processing C++ docset...")

    css_path = api_directory / ".." / ".." / "Include" / "CSS" / "udn_public.css"
    with open(css_path, "a") as css_file:
        css_file.write(
            """
#maincol {
    height: unset !important;
}

#page_head, #navWrapper, #splitter, #footer {
    display: none !important;
}

#contentContainer {
    margin-left: 0 !important;
}

.toc {
    display: none !important;
}
"""
        )

    html_files = list(api_directory.glob("**/*.html"))

    return set(
        chain(
            *process_map(
                process_cpp_html_file,
                html_files,
                chunksize=16,
            )
        )
    )


def process_blueprint_html_file(
    html_path: Path,
    collectors: Tuple = COLLECTORS_BLUEPRINT,
    add_dash_anchors: bool = True,
) -> List[Entry]:
    """
    Process given *Unreal Engine* *Blueprint* *HTML* file using given collectors.

    Parameters
    ----------
    html_path
         *HTML* file path to collect the data from.
    collectors
        Collectors used to process the *HTML* file.
    add_dash_anchors
        Whether to add *Dash* anchors to generate a
        `TOC <https://kapeli.com/docsets#tableofcontents>`__.

    Returns
    -------
    :class:`list`
        List of *Dash* documentation entries.
    """

    logger.info('Processing "%s" file...', html_path)

    def localiser(link):
        """Update given link to point to an actual *HTML* file"""

        index_path = html_path.parent / Path(link) / "index.html"

        if not index_path.exists():
            return link

        return f"{link}/index.html"

    xml = read_xml_file(html_path)
    xml.rewrite_links(localiser)

    api_information = collect_api_information(xml)

    has_dash_anchors = len(xml.xpath('.//a[@class="dashAnchor"]')) != 0

    entries = []
    for collector in collectors:
        elements = xml.xpath(collector.xpath)
        for i, collection in enumerate(
            collector.processor(elements, api_information, html_path)
        ):
            collected_name, collected_html_path = collection

            if not Path(collected_html_path).exists():
                continue

            collected_type = collector.type

            if add_dash_anchors and not has_dash_anchors:
                anchor_element = etree.Element("a")
                anchor_element.set("class", "dashAnchor")

                anchor_element.set(
                    "name",
                    f"//apple_ref/blueprint/{collected_type}/{html.escape(collected_name)}",
                )
                elements[i].addprevious(anchor_element)

            entries.append(
                Entry(
                    cast(str, collected_name),
                    cast(str, collected_html_path),
                    cast(str, collected_type),
                )
            )

    with open(html_path, "w") as html_file:
        html_file.write(tostring(xml).decode("utf-8"))  # pyright: ignore

    return entries


def process_blueprint_docset(api_directory: Path) -> set[Entry]:
    """
    Process given *Unreal Engine* *Blueprint* docset.

    Parameters
    ----------
    api_directory
         Docset *API* path, e.g.``en-US/BlueprintAPI``.

    Returns
    -------
    :class:`set`
        Set of entries.
    """

    logger.info("Processing Blueprint docset...")

    css_path = api_directory / ".." / ".." / "Include" / "CSS" / "udn_public.css"
    with open(css_path, "a") as css_file:
        css_file.write(
            """
#maincol {
    height: unset !important;
}

#page_head, #navWrapper, #splitter, #footer {
    display: none !important;
}

#contentContainer {
    margin-left: 0 !important;
}

.toc {
    display: none !important;
}
"""
        )

    html_files = list(api_directory.glob("**/*.html"))

    return set(
        chain(
            *process_map(
                process_blueprint_html_file,
                html_files,
                max_workers=multiprocessing.cpu_count() - 2,
                chunksize=16,
            )
        )
    )


def generate_database(
    database_path: Path, documents_directory: Path, entries: set[Entry]
) -> None:
    """
    Generate the *SQLite3* database storing the *Dash* entries.

    Parameters
    ----------
    database_path
        Path of the *SQLite3* database.
    documents_directory
        Path of the documents directory, e.g.
        ``UnrealEngineCpp.docset/Contents/Resources/Documents``.
    entries
        Entries to add to the *SQLite3* database.
    """

    logger.info("Creating Sqlite3 database...")

    database = sqlite3.connect(database_path)

    cursor = database.cursor()

    try:
        cursor.execute(
            "CREATE TABLE searchIndex(id INTEGER PRIMARY KEY, name TEXT, type TEXT, path TEXT);"
        )
        cursor.execute("CREATE UNIQUE INDEX anchor ON searchIndex (name, type, path);")
    except sqlite3.OperationalError as error:
        logging.warning(str(error))

    documents_directory = f"{documents_directory}/".replace("\\", "/")

    for entry in sorted(entries, key=lambda x: x.name):
        cursor.execute(
            "INSERT OR IGNORE INTO searchIndex(name, type, path) VALUES (?,?,?)",
            (
                entry.name,
                entry.type,
                entry.path.replace("\\", "/").replace(documents_directory, ""),
            ),
        )

    database.commit()
    database.close()


def generate_plist(path: Path, mapping: List[Tuple[str, str, str]]) -> None:
    """
    Generate the *PLIST* file for *Dash*.

    Parameters
    ----------
    path
        Path of the *PLIST* file, e.g.
        ``UnrealEngineCpp.docset/Contents/Info.plist``.
    mapping
        Mapping of the data to store in the *PLIST* file.
    """

    logger.info('Generating "%s" plist file...', path)

    plist_element = ET.Element("plist")
    plist_element.set("version", "1.0")

    mapping_element = ET.SubElement(plist_element, "dict")

    for key, type_, value in mapping:
        key_element = ET.SubElement(mapping_element, "key")
        key_element.text = key
        if type_ in ["string", "true", "false"]:
            value_element = ET.SubElement(mapping_element, type_)
            if type_ == "string":
                value_element.text = value

    xml = minidom.parseString(ET.tostring(plist_element, "utf-8")).toprettyxml(
        indent="\t"
    )
    xml = xml.split("\n", 1)[1]

    header = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
    )

    with open(path, "w") as plist_file:
        plist_file.write(header)
        plist_file.write(xml)


@click.command()
@click.option(
    "--input",
    required=True,
    type=click.Path(exists=True),
    help='Input "tgz" file to generate the docset from.',
)
@click.option(
    "--output",
    required=True,
    type=click.Path(exists=True),
    help="Output directory to generate to.",
)
def generate_docset(input: str, output: str) -> None:
    """
    Generate the *Dash* docset from given input *Unreal Engine* *tgz* file.

    Parameters
    ----------
    input
        *Unreal Engine* *tgz* file.
    output
        *Dash* docset output directory.
    """

    if "blueprint" in Path(input).stem.lower():
        docset_type = "blueprint"
    elif "cpp" in Path(input).stem.lower():
        docset_type = "cpp"
    else:
        logging.error("Unsupported docset type, exiting!")
        return

    docset_name = f"UnrealEngine{docset_type.title()}.docset"
    docset_directory = Path(output) / docset_name
    contents_directory = docset_directory / "Contents"
    resources_directory = contents_directory / "Resources"
    documents_directory = resources_directory / "Documents"
    documents_directory.mkdir(parents=True, exist_ok=True)

    if docset_type == "blueprint":
        api_directory = documents_directory / "en-US" / "BlueprintAPI"
        label = "Blueprint"
        processor = process_blueprint_docset
        online = "https://docs.unrealengine.com/en-US/BlueprintAPI"
    elif docset_type == "cpp":
        api_directory = documents_directory / "en-US" / "API"
        label = "C++"
        processor = process_cpp_docset
        online = "https://docs.unrealengine.com/en-US/API"
    else:
        logging.error("Unsupported docset type, exiting!")
        return

    docset_label = f"Unreal Engine {label} Docset"

    logger.info('Extracting "%s" archive to "%s"...', input, documents_directory)
    setuptools.archive_util.unpack_archive(input, str(documents_directory))

    with chdir(api_directory):  # pyright: ignore
        entries = processor(api_directory)

    generate_database(
        resources_directory / "docSet.dsidx", documents_directory, entries
    )

    mapping = [
        ("CFBundleIdentifier", "string", docset_name),
        ("CFBundleName", "string", docset_label),
        ("DashDocSetDeclaredInStyle", "string", "originalName"),
        ("DashDocSetFallbackURL", "string", online),
        ("DashDocSetFamily", "string", "python"),
        ("DocSetPlatformFamily", "string", "Unreal Engine"),
        ("isDashDocset", "true", None),
        ("isJavaScriptEnabled", "true", None),
    ]

    if docset_type == "cpp":
        mapping.append(("dashIndexFilePath", "string", "en-US/API/index.html"))
    elif docset_type == "cpp":
        mapping.append(("dashIndexFilePath", "string", "en-US/BluepringAPI/index.html"))

    generate_plist(contents_directory / "Info.plist", mapping)


if __name__ == "__main__":
    logging.basicConfig()

    logging.getLogger().setLevel(logging.INFO)

    generate_docset()
