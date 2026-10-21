from pathlib import Path
import importlib.util
import unittest
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('build_mount_plugin',ROOT/'scripts'/'build_plugin.py')
builder=importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)

class NativePluginTests(unittest.TestCase):
    def test_native_model_sources_round_trip_exactly(self):
        payload=builder.render()
        root=ET.fromstring(payload)
        model=root.find('Item')
        self.assertEqual(model.get('class'),'Model')
        items=model.findall('Item')
        self.assertEqual(len(items),3)
        for item,(kind,name,file) in zip(items,builder.SOURCES):
            self.assertEqual(item.get('class'),kind)
            self.assertEqual(item.findtext('Properties/string[@name="Name"]'),name)
            self.assertEqual(item.findtext('Properties/ProtectedString[@name="Source"]'),
                             (ROOT/'scripts'/'studio'/file).read_text(encoding='utf-8-sig'))

    def test_shipped_plugin_matches_maintained_source(self):
        self.assertEqual((ROOT/'assets'/'CharacterItemMounting.rbxmx').read_bytes(),builder.render())

if __name__=='__main__':unittest.main()
