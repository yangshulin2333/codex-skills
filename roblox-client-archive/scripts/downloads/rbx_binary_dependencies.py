"""Read explicit asset URIs from Roblox binary string properties.

Format reference: https://dom.rojo.space/binary.html
This is a bounded offline reader, not a script interpreter or full DOM decoder.
"""
from collections import Counter
from pathlib import Path
import hashlib
import re
import struct

MAX_FILE = 32 * 1024 * 1024
MAX_CHUNK = 32 * 1024 * 1024
URI_RE = re.compile(rb'(?:rbxassetid://\d+|rbx(?:asset|thumb)://[A-Za-z0-9_./%+?&=:#~-]+|https?://[A-Za-z0-9_./%+?&=:#~-]+)', re.I)


class Reader:
    def __init__(self, data):
        self.data, self.pos = data, 0

    def take(self, length):
        if length < 0 or self.pos + length > len(self.data):
            raise ValueError("truncated binary field")
        value = self.data[self.pos:self.pos + length]
        self.pos += length
        return value

    def u8(self):
        return self.take(1)[0]

    def u32(self):
        return struct.unpack("<I", self.take(4))[0]

    def string(self):
        length = self.u32()
        start = self.pos
        return start, self.take(length)


def lz4_block(data, expected):
    source, result = Reader(data), bytearray()
    while source.pos < len(data):
        token = source.u8()
        literal_length = token >> 4
        if literal_length == 15:
            extension = 255
            while extension == 255:
                extension = source.u8()
                literal_length += extension
        if len(result) + literal_length > expected:
            raise ValueError("LZ4 literals exceed declared chunk length")
        result.extend(source.take(literal_length))
        if source.pos == len(data):
            break
        offset = struct.unpack("<H", source.take(2))[0]
        if offset == 0 or offset > len(result):
            raise ValueError("invalid LZ4 back-reference")
        match_length = (token & 15) + 4
        if (token & 15) == 15:
            extension = 255
            while extension == 255:
                extension = source.u8()
                match_length += extension
        if len(result) + match_length > expected:
            raise ValueError("LZ4 matches exceed declared chunk length")
        while match_length:
            amount = min(offset, match_length)
            result.extend(result[-offset:-offset + amount] if amount < offset else result[-offset:])
            match_length -= amount
    if len(result) != expected:
        raise ValueError("LZ4 output length differs from declared chunk length")
    return bytes(result)


def inspect(path):
    path = Path(path)
    if path.stat().st_size > MAX_FILE:
        return {"isBinaryModel": False, "references": [], "notes": ["binary dependency scan limited to 32 MiB"]}
    data = path.read_bytes()
    report = {"isBinaryModel": data.startswith(b"<roblox!"), "fileSha256": hashlib.sha256(data).hexdigest(),
              "references": [], "notes": [], "chunkCounts": {}, "scannedStringCount": 0}
    if not report["isBinaryModel"]:
        return report
    if len(data) < 32 or data[8:14] != b"\x89\xff\r\n\x1a\n" or data[14:16] != b"\0\0":
        report["notes"].append("unsupported binary model header")
        return report
    cursor, class_info, refs, counts = 32, {}, [], Counter()

    def strings(value, evidence):
        offset, raw = value
        report["scannedStringCount"] += 1
        for match in URI_RE.finditer(raw):
            refs.append({"uri": match.group().decode("ascii"), "stringByteOffsetWithinChunk": offset,
                         "uriByteOffsetWithinString": match.start(), **evidence})

    while cursor < len(data):
        start = cursor
        if cursor + 16 > len(data):
            report["notes"].append("truncated chunk header")
            break
        name, compressed, uncompressed, _ = struct.unpack("<4sIII", data[cursor:cursor + 16])
        cursor += 16
        body_size = compressed or uncompressed
        if cursor + body_size > len(data):
            report["notes"].append("truncated chunk body")
            break
        body = data[cursor:cursor + body_size]
        cursor += body_size
        chunk_name = name.rstrip(b"\0").decode("ascii", "replace")
        counts[chunk_name] += 1
        if chunk_name == "END":
            if body != b"</roblox>":
                report["notes"].append("unexpected END marker")
            break
        if chunk_name not in {"INST", "PROP", "SSTR"}:
            continue
        try:
            if uncompressed > MAX_CHUNK:
                raise ValueError("chunk scan limited to 32 MiB")
            if compressed and body.startswith(b"\x28\xb5\x2f\xfd"):
                try:
                    import zstandard
                except ImportError:
                    raise ValueError("ZSTD chunk not decoded; optional zstandard unavailable")
                body = zstandard.ZstdDecompressor().decompress(body, max_output_size=MAX_CHUNK)
                if len(body) != uncompressed:
                    raise ValueError("ZSTD chunk length mismatch")
            elif compressed:
                body = lz4_block(body, uncompressed)
            r = Reader(body)
            evidence = {"chunk": chunk_name, "chunkFileOffset": start}
            if chunk_name == "INST":
                class_id = r.u32()
                _, class_name = r.string()
                r.u8()
                count = r.u32()
                if count > 1_000_000:
                    raise ValueError("class count limit exceeded")
                class_info[class_id] = (class_name.decode("utf-8", "replace"), count)
            elif chunk_name == "SSTR":
                if r.u32() != 0:
                    raise ValueError("unsupported SSTR version")
                count = r.u32()
                if count > 1_000_000:
                    raise ValueError("shared string count limit exceeded")
                for index in range(count):
                    r.take(16)
                    strings(r.string(), {**evidence, "sharedStringIndex": index})
            else:
                class_id = r.u32()
                _, property_name = r.string()
                value_type = r.u8()
                if class_id not in class_info:
                    raise ValueError("PROP class ID not declared")
                class_name, count = class_info[class_id]
                evidence.update(className=class_name, property=property_name.decode("utf-8", "replace"),
                                propertyType=value_type)
                if value_type == 1:
                    for index in range(count):
                        strings(r.string(), {**evidence, "propertyValueIndex": index})
                elif value_type == 0x20:
                    for index in range(count):
                        strings(r.string(), {**evidence, "propertyValueIndex": index, "fontField": "Family"})
                        r.take(3)
                        strings(r.string(), {**evidence, "propertyValueIndex": index, "fontField": "CachedFaceId"})
                elif value_type == 0x22:
                    r.take(count * 4)
                    uri_count = r.u32()
                    if uri_count > count:
                        raise ValueError("Content URI count exceeds instance count")
                    for index in range(uri_count):
                        strings(r.string(), {**evidence, "contentUriIndex": index})
                elif evidence["property"] in {"MeshId", "TextureID", "TextureId", "Texture", "Image",
                                                "SoundId", "AnimationId", "FontFace", "Video"}:
                    report["notes"].append(f"{class_name}.{evidence['property']} uses unparsed type {value_type}")
        except Exception as exc:
            report["notes"].append(f"{chunk_name} at {start}: {exc}")
    class_counts = Counter()
    for class_name, count in class_info.values():
        class_counts[class_name] += count
    report.update(references=refs, chunkCounts=dict(counts), classCounts=dict(class_counts))
    return report


def dependencies(path):
    report = inspect(path)
    return sorted({r["uri"] for r in report["references"]}), "; ".join(report["notes"]) or None
