import SwiftUI
import WebKit

struct WebView: UIViewRepresentable {
    let fileURL: URL
    let readAccessURL: URL

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.allowsInlineMediaPlayback = true
        let webView = WKWebView(frame: .zero, configuration: config)
        webView.scrollView.bounces = false
        webView.isOpaque = false
        webView.backgroundColor = .black
        webView.loadFileURL(fileURL, allowingReadAccessTo: readAccessURL)
        return webView
    }

    func updateUIView(_ uiView: WKWebView, context: Context) {}
}

struct ContentView: View {
    var body: some View {
        if let indexURL = Bundle.main.url(forResource: "index", withExtension: "html", subdirectory: "WebApp") {
            WebView(fileURL: indexURL, readAccessURL: indexURL.deletingLastPathComponent())
                .ignoresSafeArea()
                .statusBar(hidden: true)
        } else {
            Text("Missing web assets")
        }
    }
}
