"""Pinned Android 1.19.1 (3050) Hermes 98 recipe. Contains no official bytecode."""
import hashlib
import re
import struct
from urllib.parse import urlsplit, urlunsplit

INPUT_SHA256 = 'e4e58266c8380d6ac4696ece4f293eca872bd6dc3e470d2db33fb3d44b0f3290'
INPUT_SIZE = 23889920
BASE_SHA256 = '61f821dc88cf5939e99f9d135c57f6ef9b4aa91a916b5fab7449b20fee486e30'
HEADER = 128 + 20928 * 12
OLD_BODY = 9817452
RECIPE = 'gateway-send-v2'
SEND_SOURCE = 13618478


def origin(value, *, probe=False):
    value = value.strip()
    url = urlsplit(value)
    if (any(ord(c) < 33 for c in value) or not url.hostname or url.username or url.password
            or url.path not in ('', '/') or url.query or url.fragment or '?' in value or '#' in value
            or (url.scheme != 'https' and not (probe and url.scheme == 'http' and url.hostname == '127.0.0.1'))):
        raise ValueError('Host must be an HTTPS origin without credentials, path, query, or fragment')
    port = url.port  # Reject malformed/out-of-range ports.
    if port == 0:
        raise ValueError('Invalid port')
    host = url.hostname.encode('idna').decode('ascii').lower()
    if ':' in host:
        host = '[' + host + ']'
    if port is not None and port != (443 if url.scheme == 'https' else 80):
        host += ':' + str(port)
    result = urlunsplit((url.scheme, host, '', '', ''))
    if len(result) > 512:
        raise ValueError('Host origin exceeds 512 bytes')
    return result


def validate(data):
    if len(data) != INPUT_SIZE or hashlib.sha256(data).hexdigest() != INPUT_SHA256:
        raise ValueError('Unsupported original bundle; refusing to apply offsets')
    if hashlib.sha1(data[:-20]).digest() != data[-20:]:
        raise ValueError('Invalid Hermes checksum')


def patch(data, address, token, *, probe=False, gateway_send=True):
    validate(data)
    address = origin(address, probe=probe)
    if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{32,256}', token):
        raise ValueError('Invalid Host device token')
    u32 = lambda offset: struct.unpack_from('<I', data, offset)[0]
    if (u32(8) != 98 or u32(32) != len(data) or (u32(HEADER) & 0x1ffffff) != OLD_BODY
            or (u32(HEADER + 4) & 0x3fff) != 4 or data[OLD_BODY:OLD_BODY + 4] != bytes([147, 0, 118, 0])):
        raise ValueError('Unexpected function header')
    table = 128 + u32(40) * 12 + u32(44) * 4 + u32(48) * 4
    overflow = table + u32(52) * 4
    storage = overflow + u32(56) * 8
    strings = {}
    for i in range(u32(52)):
        entry = u32(table + i * 4)
        offset, length, utf16 = (entry >> 1) & 0x7fffff, entry >> 24, entry & 1
        if length == 255:
            offset, length = struct.unpack_from('<II', data, overflow + offset * 8)
        if length > 5:
            continue
        value = data[storage + offset:storage + offset + length * (2 if utf16 else 1)].decode(
            'utf-16-le' if utf16 else 'utf-8', errors='surrogatepass')
        strings.setdefault(value, i)
    if strings['url'] != 32 or strings['token'] != 244:
        raise ValueError('Unexpected string table')
    body = bytearray([4, 0])  # NewObject r0

    def string(register, value):
        index = strings[value]
        body.extend(struct.pack('<BBH' if index < 65536 else '<BBI', 144 if index < 65536 else 145, register, index))

    for cache, (key, value) in enumerate([('url', address), ('token', token)]):
        string(1, '')
        for character in value:
            if character in strings:
                string(2, character)
            elif character in '0123456789':
                body.extend([139, 2, int(character)])
            else:
                raise ValueError('Unsupported character in Host origin')
            body.extend([30, 1, 1, 2])  # Add
        body.extend(struct.pack('<BBBBH', 86, 0, 1, cache, strings[key]))  # DefineOwnById
    body.extend([118, 0])
    result = bytearray(data[:-20])
    result.extend(bytes((-len(result)) % 4))
    offset = len(result)
    if offset >= 2**25 or len(body) >= 2**14:
        raise ValueError('Function header overflow')
    result.extend(body)
    struct.pack_into('<II', result, HEADER, (u32(HEADER) & ~0x1ffffff) | offset,
                     (u32(HEADER + 4) & ~0x3fff) | len(body))
    result[HEADER + 8] = max(result[HEADER + 8], 3)
    result[HEADER + 10] = (result[HEADER + 10] & 0xc0) | 2
    if gateway_send:
        # buildLive (f25715) unconditionally supplies the cloud BackendClient sender,
        # even with DevGatewayOverride. r1 is undefined throughout this function.
        # Passing undefined lets stampSender (f25720) preserve it and ChatSession
        # (f27940) select its existing gateway.sendPrompt adapter (f55296).
        # Only the source register changes; lengths, branches and shared bodies stay
        # intact. This recipe always installs an explicit gateway override above.
        expected = struct.pack('<BBBBH', 86, 11, 24, 27, 35277)
        if data[SEND_SOURCE:SEND_SOURCE + 6] != expected or data[13615571:13615573] != bytes([147, 1]):
            raise ValueError('Unexpected message sender instruction')
        result[SEND_SOURCE + 2] = 1
    struct.pack_into('<I', result, 32, len(result) + 20)
    result.extend(hashlib.sha1(result).digest())
    return bytes(result)
