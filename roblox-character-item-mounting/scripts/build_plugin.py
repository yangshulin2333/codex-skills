#!/usr/bin/env python3
"""Build/check a native Roblox XML local-plugin model from maintained sources.

Offline, Python standard library only. No Studio/network/config access.
Default writes only assets/CharacterItemMounting.rbxmx inside this skill.
Use --check for a read-only reproducibility check.
"""
from pathlib import Path
import argparse
import sys
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
SOURCES=(('ModuleScript','MountCore','MountCore.lua'),
         ('ModuleScript','MountWorkbench','MountWorkbench.lua'),
         ('Script','PluginMain','PluginMain.server.lua'))

def render(root=ROOT):
    document=ET.Element('roblox',{'version':'4'})
    ET.SubElement(document,'External').text='null'
    ET.SubElement(document,'External').text='nil'
    model=ET.SubElement(document,'Item',{'class':'Model','referent':'RBX0'})
    props=ET.SubElement(model,'Properties')
    ET.SubElement(props,'string',{'name':'Name'}).text='CharacterItemMounting'
    for index,(kind,name,file) in enumerate(SOURCES,1):
        source=(root/'scripts'/'studio'/file).read_text(encoding='utf-8-sig')
        item=ET.SubElement(model,'Item',{'class':kind,'referent':f'RBX{index}'})
        props=ET.SubElement(item,'Properties')
        ET.SubElement(props,'string',{'name':'Name'}).text=name
        ET.SubElement(props,'ProtectedString',{'name':'Source'}).text=source
        if kind=='Script':ET.SubElement(props,'bool',{'name':'Disabled'}).text='false'
    ET.indent(document,space='  ')
    return ET.tostring(document,encoding='utf-8',xml_declaration=True)+b'\n'

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check',action='store_true')
    args=parser.parse_args()
    target=ROOT/'assets'/'CharacterItemMounting.rbxmx'
    expected=render()
    if args.check:
        if not target.is_file() or target.read_bytes()!=expected:
            print('PLUGIN_SOURCE_MISMATCH: run python scripts/build_plugin.py',file=sys.stderr)
            return 1
        print('PLUGIN_REPRODUCIBLE_OK')
    else:
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(expected)
        print(f'PLUGIN_BUILT bytes={len(expected)}')
    return 0

if __name__=='__main__':sys.exit(main())
