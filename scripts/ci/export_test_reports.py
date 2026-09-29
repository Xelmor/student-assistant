"""Export JUnit status/timing only: never upload captured logs, cookies or traces."""
import argparse
from pathlib import Path
import xml.etree.ElementTree as ET


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    args.destination.mkdir(parents=True, exist_ok=True)
    for source in sorted(args.source.glob('*.xml')):
        root = ET.Element('testsuites')
        for original in ET.parse(source).getroot().iter('testsuite'):
            suite = ET.SubElement(root, 'testsuite', {
                key: original.attrib[key] for key in ('name', 'tests', 'errors', 'failures', 'skipped', 'time')
                if key in original.attrib})
            for original_case in original.findall('testcase'):
                case = ET.SubElement(suite, 'testcase', {
                    key: original_case.attrib[key] for key in ('classname', 'name', 'time')
                    if key in original_case.attrib})
                for status in ('failure', 'error', 'skipped'):
                    if original_case.find(status) is not None:
                        ET.SubElement(case, status, {
                            'message': 'See the Actions test step output and E2E screenshots.'})
        ET.indent(root)
        ET.ElementTree(root).write(args.destination / source.name, encoding='utf-8', xml_declaration=True)
        print(f'Exported status/timing report: {source.name}')


if __name__ == '__main__':
    main()
