from pathlib import Path

path = Path("src/client_generator.rs")
text = path.read_text()
old = """            ClientSuccessBody::EventStream => {\n                quote! { impl futures_util::Stream<Item = Result<bytes::Bytes, reqwest::Error>> }\n            }\n"""
new = """            ClientSuccessBody::EventStream => {\n                quote! {\n                    impl futures_util::Stream<Item = Result<bytes::Bytes, reqwest::Error>> + 'static\n                }\n            }\n"""
if text.count(old) != 1:
    raise SystemExit(f"expected exactly one SSE return ABI marker, found {text.count(old)}")
path.write_text(text.replace(old, new))
