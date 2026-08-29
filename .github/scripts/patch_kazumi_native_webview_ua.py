from pathlib import Path

ROOT = Path('Kazumi')
path = ROOT / 'lib/pages/info/source_captcha_flow.dart'
text = path.read_text(encoding='utf-8')

replacements = [
    ("import 'package:kazumi/utils/http_headers.dart';\n", ""),
    ("  late final String _userAgent;\n", ""),
    ("""  @override
  void initState() {
    super.initState();
    _userAgent = getRandomUA();
  }

""", ""),
    ("      final userAgent = userAgentValue?.toString() ?? _userAgent;\n",
     "      final userAgent = userAgentValue?.toString() ?? '';\n"),
    ("                  userAgent: _userAgent,\n", ""),
]

for old, new in replacements:
    if old not in text:
        raise RuntimeError(f'patch target not found: {old[:100]!r}')
    text = text.replace(old, new, 1)

path.write_text(text, encoding='utf-8')

pubspec = ROOT / 'pubspec.yaml'
pub = pubspec.read_text(encoding='utf-8')
old_version = 'version: 2.3.0+20301\n'
new_version = 'version: 2.3.0+20302\n'
if old_version not in pub:
    raise RuntimeError('expected custom build version not found')
pubspec.write_text(pub.replace(old_version, new_version, 1), encoding='utf-8')

print('Native WebView2 UA patch applied successfully.')
