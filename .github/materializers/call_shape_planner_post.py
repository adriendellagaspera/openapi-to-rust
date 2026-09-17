from pathlib import Path
import re

path = Path("src/client_generator.rs")
text = path.read_text()


def replace_once(old: str, new: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected one match, got {count}: {old[:120]!r}")
    text = text.replace(old, new, 1)


# Builders share the exact operation/call-shape plan used by flat methods,
# including collision-safe names and selected return types.
replace_once(
    "        let (operation_builders, builder_entries) =\n            self.generate_operation_builders(analysis, operations);",
    "        let (operation_builders, builder_entries) =\n            self.generate_operation_builders(analysis, &method_plans);",
)

start = text.index("    fn generate_operation_builders(")
end = text.index("    #[allow(clippy::too_many_arguments)]", start)
block = text[start:end]
block = block.replace(
    "        operations: &[&OperationInfo],",
    "        plans: &[ClientOperationMethodPlan<'_>],",
    1,
)
block, count = re.subn(
    r"        let mut used_entry_methods: std::collections::HashSet<String> = operations\n            \.iter\(\)\n            \.map\(\|operation\| self\.get_method_name\(operation\)\.to_string\(\)\)\n            \.collect\(\);",
    "        let mut used_entry_methods = std::collections::HashSet::new();\n"
    "        for plan in plans {\n"
    "            for shape in &plan.call_shapes {\n"
    "                used_entry_methods.insert(shape.rust_method_name.clone());\n"
    "            }\n"
    "            if let Some(method_name) = &plan.multipart_filename_method_name {\n"
    "                used_entry_methods.insert(method_name.to_string());\n"
    "            }\n"
    "        }",
    block,
    count=1,
)
if count != 1:
    raise SystemExit(f"used_entry_methods replacement count: {count}")

marker = "        for operation in operations {"
first = block.find(marker)
if first < 0:
    raise SystemExit("first operation loop not found")
block = (
    block[:first]
    + "        for plan in plans {\n            let operation = plan.operation;"
    + block[first + len(marker) :]
)
second = block.find(marker)
if second < 0:
    raise SystemExit("second operation loop not found")
block = (
    block[:second]
    + "        for plan in plans {\n"
    + "            let operation = plan.operation;\n"
    + "            let Some(base_shape) = plan.call_shapes.first() else {\n"
    + "                continue;\n"
    + "            };"
    + block[second + len(marker) :]
)
block = block.replace(
    "            let flat_method = self.get_method_name(operation);",
    "            let flat_method = Self::to_field_ident(&base_shape.rust_method_name);",
    1,
)
block = block.replace(
    "                analysis,\n                operation,\n                &allocated_params,",
    "                operation,\n                base_shape,\n                &allocated_params,",
    1,
)
text = text[:start] + block + text[end:]

replace_once(
    "        analysis: &SchemaAnalysis,\n        operation: &OperationInfo,\n        allocated_params: &[AllocatedOperationParam<'_>],",
    "        operation: &OperationInfo,\n        base_shape: &ClientCallShapePlan,\n        allocated_params: &[AllocatedOperationParam<'_>],",
)

# The emitted source consumes the exact Rust type string stored on the plan.
# Invalid internal planning becomes generated compile_error! tokens instead of
# panicking inside the generator.
helper = (
    "    fn planned_success_type_tokens(call_shape: &ClientCallShapePlan) -> TokenStream {\n"
    "        match syn::parse_str::<syn::Type>(&call_shape.success_type) {\n"
    "            Ok(response_type) => quote! { #response_type },\n"
    "            Err(error) => error.to_compile_error(),\n"
    "        }\n"
    "    }\n\n"
)
success_guard = text.index("    fn success_status_guard(")
text = text[:success_guard] + helper + text[success_guard:]

replace_once(
    "        let response_type = self.get_response_type(analysis, operation);",
    "        let response_type = Self::planned_success_type_tokens(base_shape);",
)
replace_once(
    "        let response_type: syn::Type = syn::parse_str(&call_shape.success_type)\n            .expect(\"planned client success type must be valid Rust\");",
    "        let response_type = Self::planned_success_type_tokens(call_shape);",
)

path.write_text(text)
