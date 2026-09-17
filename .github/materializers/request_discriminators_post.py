from pathlib import Path

client = Path("src/client_generator.rs")
text = client.read_text()
text = text.replace(
    "    RequestDiscriminatorRule, RequestDiscriminatorTransport, RequestDiscriminatorValue,\n",
    "    RequestDiscriminatorTransport, RequestDiscriminatorValue,\n",
    1,
)
old = '''                RequestDiscriminatorValue::Integer(_) => matches!(
                    rust_type.as_str(),
                    "i8" | "i16" | "i32" | "i64" | "isize" | "u8" | "u16" | "u32" | "u64" | "usize"
                ),'''
new = '''                RequestDiscriminatorValue::Integer(value) => match rust_type.as_str() {
                    "i8" => i8::try_from(*value).is_ok(),
                    "i16" => i16::try_from(*value).is_ok(),
                    "i32" => i32::try_from(*value).is_ok(),
                    "i64" => true,
                    "u8" => u8::try_from(*value).is_ok(),
                    "u16" => u16::try_from(*value).is_ok(),
                    "u32" => u32::try_from(*value).is_ok(),
                    "u64" => u64::try_from(*value).is_ok(),
                    _ => false,
                },'''
if old not in text:
    raise SystemExit("integer compatibility anchor not found")
text = text.replace(old, new, 1)
client.write_text(text)

test = Path("tests/client_request_discriminator_test.rs")
text = test.read_text()
old = 'sse_body.find(".json(&request)").expect("request serialization")'
new = 'sse_body.find("serde_json::to_vec(&request)").expect("request serialization")'
if old not in text:
    raise SystemExit("serialization assertion anchor not found")
test.write_text(text.replace(old, new, 1))
