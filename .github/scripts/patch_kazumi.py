from pathlib import Path

ROOT = Path('Kazumi')


def replace_once(relative_path: str, old: str, new: str) -> None:
    path = ROOT / relative_path
    text = path.read_text(encoding='utf-8')
    if old not in text:
        raise RuntimeError(f'patch target not found in {relative_path}: {old[:120]!r}')
    path.write_text(text.replace(old, new, 1), encoding='utf-8')


# 1) Treat a 403 search response as a verification requirement when the rule
# explicitly opts into anti-crawler handling. This lets the existing source UI
# surface a verification action instead of failing before the captcha flow.
replace_once(
    'lib/services/plugin/rule_engine.dart',
    """    } catch (error, stackTrace) {\n      if (_isCancellation(error)) rethrow;\n      _logFailure(config, phase, error, stackTrace);\n      throw wrapError(error);\n    }\n""",
    """    } catch (error, stackTrace) {\n      if (_isCancellation(error)) rethrow;\n      if (phase == 'search request' &&\n          config.antiCrawlerConfig.enabled &&\n          error is NetworkException &&\n          error.type == NetworkExceptionType.badResponse &&\n          error.statusCode == 403) {\n        if (_logFailures) {\n          KazumiLogger().i(\n            'Plugin: ${config.pluginName} search returned 403; ' \n            'requesting WebView verification',\n          );\n        }\n        throw CaptchaRequiredException(config.pluginName);\n      }\n      _logFailure(config, phase, error, stackTrace);\n      throw wrapError(error);\n    }\n""",
)

# 2) Add a non-automated verification mode. Type 4 opens a visible WebView and
# lets the user complete the site's own verification UI manually.
replace_once(
    'lib/plugins/anti_crawler_config.dart',
    """  static const int customJavaScript = 3;\n}\n""",
    """  static const int customJavaScript = 3;\n\n  /// Visible WebView. The user completes the site's verification manually.\n  static const int manualWebView = 4;\n}\n""",
)

# 3) The upstream project depends on the platform packages directly because its
# current captcha WebView is headless. Add the umbrella package so the visible
# InAppWebView widget is available for manual verification.
replace_once(
    'pubspec.yaml',
    """  flutter_inappwebview_platform_interface: ^1.3.0+1\n""",
    """  flutter_inappwebview: ^6.1.5\n  flutter_inappwebview_platform_interface: ^1.3.0+1\n""",
)

# 4) Extend SourceCaptchaFlow with a full-screen interactive WebView that saves
# cookies + UA into the same per-rule cookie jar used by normal search requests.
replace_once(
    'lib/pages/info/source_captcha_flow.dart',
    """import 'package:flutter/material.dart';\n""",
    """import 'package:flutter/material.dart';\nimport 'package:flutter_inappwebview/flutter_inappwebview.dart';\n""",
)
replace_once(
    'lib/pages/info/source_captcha_flow.dart',
    """import 'package:kazumi/services/plugin/captcha_verification_service.dart';\n""",
    """import 'package:kazumi/services/plugin/captcha_verification_service.dart';\nimport 'package:kazumi/services/plugin/plugin_cookie_manager.dart';\nimport 'package:kazumi/utils/http_headers.dart';\n""",
)
replace_once(
    'lib/pages/info/source_captcha_flow.dart',
    """    switch (plugin.antiCrawlerConfig.captchaType) {\n      case CaptchaType.customJavaScript:\n""",
    """    switch (plugin.antiCrawlerConfig.captchaType) {\n      case CaptchaType.manualWebView:\n        _startManualWebView(plugin, searchUrl);\n      case CaptchaType.customJavaScript:\n""",
)
replace_once(
    'lib/pages/info/source_captcha_flow.dart',
    """  void _startCaptchaInput(Plugin plugin, String searchUrl) {\n""",
    """  void _startManualWebView(Plugin plugin, String searchUrl) {\n    bool verified = false;\n\n    _timer?.cancel();\n    _timer = null;\n    _service?.dispose();\n    _service = null;\n\n    KazumiDialog.show(\n      onDismiss: () {\n        if (!verified) onCancelled(plugin);\n      },\n      builder: (context) => _ManualVerifyDialog(\n        pluginName: plugin.name,\n        url: searchUrl,\n        onVerified: (pageHtml) {\n          verified = true;\n          KazumiDialog.dismiss();\n          onVerified(plugin, pageHtml);\n        },\n      ),\n    );\n  }\n\n  void _startCaptchaInput(Plugin plugin, String searchUrl) {\n""",
)
replace_once(
    'lib/pages/info/source_captcha_flow.dart',
    """class _VerifyDialogFrame extends StatelessWidget {\n""",
    r'''class _ManualVerifyDialog extends StatefulWidget {
  const _ManualVerifyDialog({
    required this.pluginName,
    required this.url,
    required this.onVerified,
  });

  final String pluginName;
  final String url;
  final void Function(String pageHtml) onVerified;

  @override
  State<_ManualVerifyDialog> createState() => _ManualVerifyDialogState();
}

class _ManualVerifyDialogState extends State<_ManualVerifyDialog> {
  InAppWebViewController? _controller;
  late final String _userAgent;
  int _progress = 0;
  bool _saving = false;

  @override
  void initState() {
    super.initState();
    _userAgent = getRandomUA();
  }

  Future<void> _finishVerification() async {
    final controller = _controller;
    if (controller == null || _saving) return;
    setState(() => _saving = true);

    try {
      final currentUrl = await controller.getUrl();
      final cookieUrl = currentUrl ?? WebUri(widget.url);
      final cookies =
          await CookieManager.instance().getCookies(url: cookieUrl);
      final cookieString =
          cookies.map((cookie) => '${cookie.name}=${cookie.value}').join('; ');
      final userAgentValue = await controller.evaluateJavascript(
        source: 'navigator.userAgent',
      );
      final pageHtmlValue = await controller.evaluateJavascript(
        source: 'document.documentElement.outerHTML',
      );
      final userAgent = userAgentValue?.toString() ?? _userAgent;
      final pageHtml = pageHtmlValue?.toString() ?? '';
      final cookiePageUrl = cookieUrl.toString();

      await PluginCookieManager.instance.saveFromWebView(
        widget.pluginName,
        cookiePageUrl,
        cookieString,
        userAgent: userAgent,
      );

      if (!mounted) return;
      widget.onVerified(pageHtml);
    } catch (error) {
      if (!mounted) return;
      setState(() => _saving = false);
      KazumiDialog.showToast(message: '保存验证状态失败: $error');
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Dialog.fullscreen(
      child: Scaffold(
        appBar: AppBar(
          title: Text('${widget.pluginName} 手动验证'),
          leading: IconButton(
            onPressed: _saving ? null : () => KazumiDialog.dismiss(),
            icon: const Icon(Icons.close),
            tooltip: '取消',
          ),
        ),
        body: Column(
          children: [
            if (_progress < 100)
              LinearProgressIndicator(value: _progress / 100),
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 10, 16, 10),
              child: Text(
                '请在下面的网页中亲自完成站点验证。看到正常页面或搜索结果后，点击“完成验证”。',
                style: theme.textTheme.bodyMedium,
              ),
            ),
            Expanded(
              child: InAppWebView(
                initialUrlRequest: URLRequest(url: WebUri(widget.url)),
                initialSettings: InAppWebViewSettings(
                  userAgent: _userAgent,
                  javaScriptEnabled: true,
                  cacheEnabled: true,
                  domStorageEnabled: true,
                  databaseEnabled: true,
                ),
                onWebViewCreated: (controller) {
                  _controller = controller;
                },
                onProgressChanged: (controller, progress) {
                  if (mounted) setState(() => _progress = progress);
                },
              ),
            ),
            SafeArea(
              top: false,
              child: Padding(
                padding: const EdgeInsets.fromLTRB(16, 8, 16, 12),
                child: Row(
                  children: [
                    TextButton(
                      onPressed:
                          _saving ? null : () => KazumiDialog.dismiss(),
                      child: const Text('取消'),
                    ),
                    const Spacer(),
                    FilledButton.icon(
                      onPressed: _saving ? null : _finishVerification,
                      icon: _saving
                          ? const SizedBox.square(
                              dimension: 18,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : const Icon(Icons.check),
                      label: Text(_saving ? '正在保存' : '完成验证'),
                    ),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _VerifyDialogFrame extends StatelessWidget {
''',
)

# 5) Make the rule test page use the same manual verification flow. After the
# user completes verification it reruns the test with the captured cookies/UA.
replace_once(
    'lib/pages/plugin_editor/plugin_test_page.dart',
    """import 'package:kazumi/services/logging/logger.dart';\n""",
    """import 'package:kazumi/services/logging/logger.dart';\nimport 'package:kazumi/pages/info/source_captcha_flow.dart';\n""",
)
replace_once(
    'lib/pages/plugin_editor/plugin_test_page.dart',
    """  int? _shownFragmentIndex;\n\n  bool get _hasSearchRaw => searchRaw.isNotEmpty;\n""",
    """  int? _shownFragmentIndex;\n  late final SourceCaptchaFlow _captchaFlow;\n\n  bool get _hasSearchRaw => searchRaw.isNotEmpty;\n""",
)
replace_once(
    'lib/pages/plugin_editor/plugin_test_page.dart',
    """    plugin = widget.plugin;\n    testKeywordController.addListener(\n""",
    """    plugin = widget.plugin;\n    _captchaFlow = SourceCaptchaFlow(\n      onVerified: (_, __) {\n        if (mounted) startTest();\n      },\n      onCancelled: (_) {},\n    );\n    testKeywordController.addListener(\n""",
)
replace_once(
    'lib/pages/plugin_editor/plugin_test_page.dart',
    """    _testRoadsCancelToken?.cancel();\n    testKeywordController.dispose();\n""",
    """    _testRoadsCancelToken?.cancel();\n    _captchaFlow.dispose();\n    testKeywordController.dispose();\n""",
)
replace_once(
    'lib/pages/plugin_editor/plugin_test_page.dart',
    """    } catch (e, stack) {\n      KazumiLogger().e(\"PluginTest: test failed\", error: e, stackTrace: stack);\n""",
    """    } on CaptchaRequiredException {\n      if (mounted) {\n        setState(() => isTesting = false);\n        _captchaFlow.start(plugin, keyword);\n      }\n      return;\n    } catch (e, stack) {\n      KazumiLogger().e(\"PluginTest: test failed\", error: e, stackTrace: stack);\n""",
)

# Mark this as a custom build so it is easy to distinguish from upstream 2.3.0.
replace_once(
    'pubspec.yaml',
    "version: 2.3.0+20300\n",
    "version: 2.3.0+20301\n",
)

print('Kazumi 403/manual verification patch applied successfully.')
