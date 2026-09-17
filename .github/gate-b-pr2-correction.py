from pathlib import Path

path = Path("src/client_generator.rs")
source = path.read_text()

old = '''struct BodyModelPlan {
    body_ident: syn::Ident,
    body_type: TokenStream,
    required_construction: RequiredBodyConstruction,
    optional_fields: Vec<BodyFieldPlan>,
}
'''
new = old + '''
#[derive(Clone)]
struct ClientOperationMethodPlan<'a> {
    operation: &'a OperationInfo,
    method_name: syn::Ident,
    multipart_filename_method_name: Option<syn::Ident>,
}
'''
assert old in source
source = source.replace(old, new, 1)

old = '''        let methods: Vec<TokenStream> = operations
            .iter()
            .copied()
            .map(|op| self.generate_single_operation_method(analysis, op))
            .collect();

        let (operation_builders, builder_entries) =
            self.generate_operation_builders(analysis, operations);
'''
new = '''        let method_plans = self.plan_client_operation_methods(operations);
        let methods: Vec<TokenStream> = method_plans
            .iter()
            .map(|plan| self.generate_single_operation_method(analysis, plan))
            .collect();

        let (operation_builders, builder_entries) =
            self.generate_operation_builders(analysis, operations);
'''
assert old in source
source = source.replace(old, new, 1)

marker = '''    fn generate_operation_builders(
        &self,
        analysis: &SchemaAnalysis,
        operations: &[&OperationInfo],
    ) -> (Vec<TokenStream>, Vec<TokenStream>) {
'''
planner = '''    fn plan_client_operation_methods<'a>(
        &self,
        operations: &[&'a OperationInfo],
    ) -> Vec<ClientOperationMethodPlan<'a>> {
        let mut used_method_names: std::collections::HashSet<String> = operations
            .iter()
            .map(|operation| self.get_method_name(operation).to_string())
            .collect();

        operations
            .iter()
            .map(|operation| {
                let operation = *operation;
                let method_name = self.get_method_name(operation);
                let multipart_filename_method_name = matches!(
                    operation.request_body.as_ref(),
                    Some(crate::analysis::RequestBodyContent::Multipart { .. })
                )
                .then(|| {
                    let preferred = format!("{method_name}_with_multipart_filenames");
                    let allocated = Self::allocate_name(&preferred, &mut used_method_names);
                    Self::to_field_ident(&allocated)
                });
                ClientOperationMethodPlan {
                    operation,
                    method_name,
                    multipart_filename_method_name,
                }
            })
            .collect()
    }

'''
assert marker in source
source = source.replace(marker, planner + marker, 1)

old = '''    fn generate_single_operation_method(
        &self,
        analysis: &SchemaAnalysis,
        op: &OperationInfo,
    ) -> TokenStream {
        let method_name = self.get_method_name(op);
        let base =
            self.generate_single_operation_method_variant(analysis, op, method_name.clone(), false);
        if matches!(
            op.request_body.as_ref(),
            Some(crate::analysis::RequestBodyContent::Multipart { .. })
        ) {
            let filename_method = format_ident!("{}_with_multipart_filenames", method_name);
            let with_filenames =
                self.generate_single_operation_method_variant(analysis, op, filename_method, true);
            quote! {
                #base
                #with_filenames
            }
        } else {
            base
        }
    }
'''
new = '''    fn generate_single_operation_method(
        &self,
        analysis: &SchemaAnalysis,
        plan: &ClientOperationMethodPlan<'_>,
    ) -> TokenStream {
        let op = plan.operation;
        let base = self.generate_single_operation_method_variant(
            analysis,
            op,
            plan.method_name.clone(),
            false,
        );
        if let Some(filename_method) = &plan.multipart_filename_method_name {
            let with_filenames = self.generate_single_operation_method_variant(
                analysis,
                op,
                filename_method.clone(),
                true,
            );
            quote! {
                #base
                #with_filenames
            }
        } else {
            base
        }
    }
'''
assert old in source
source = source.replace(old, new, 1)

old = '''                /// Override multipart filenames for binary fields by OpenAPI wire name.
                /// Unspecified binary fields use their wire name as a deterministic fallback.
'''
new = '''                /// Override multipart filenames for binary fields by OpenAPI wire name.
                /// Unspecified binary fields retain the base method's no-filename behavior.
'''
assert old in source
source = source.replace(old, new, 1)

old = '''                MultipartClientFieldKind::RawBytes => {
                    let filename = if with_multipart_filenames {
                        quote! {
                            multipart_filenames
                                .iter()
                                .find(|(field, _)| *field == #wire_name)
                                .map(|(_, filename)| (*filename).to_string())
                                .unwrap_or_else(|| #wire_name.to_string())
                        }
                    } else {
                        quote! { #wire_name.to_string() }
                    };
                    quote! {
                        form = form.part(
                            #wire_name,
                            reqwest::multipart::Part::bytes(value.to_vec()).file_name(#filename),
                        );
                    }
                }
'''
new = '''                MultipartClientFieldKind::RawBytes if with_multipart_filenames => quote! {
                    let part = reqwest::multipart::Part::bytes(value.to_vec());
                    let part = if let Some((_, filename)) = multipart_filenames
                        .iter()
                        .find(|(field, _)| *field == #wire_name)
                    {
                        part.file_name((*filename).to_string())
                    } else {
                        part
                    };
                    form = form.part(#wire_name, part);
                },
                MultipartClientFieldKind::RawBytes => quote! {
                    form = form.part(
                        #wire_name,
                        reqwest::multipart::Part::bytes(value.to_vec()),
                    );
                },
'''
assert old in source
source = source.replace(old, new, 1)
path.write_text(source)

Path("tests/client_multipart_capabilities_test.rs").write_text(r'''use openapi_to_rust::{CodeGenerator, GeneratorConfig, SchemaAnalyzer};
use serde_json::json;
use std::path::PathBuf;

#[test]
fn repeated_scalar_fields_and_nullable_binary_parts_generate_typed_multipart()
-> Result<(), Box<dyn std::error::Error>> {
    let spec = json!({
        "openapi": "3.1.0",
        "info": {"title": "Multipart Fixture", "version": "1.0.0"},
        "paths": {
            "/uploads": {
                "post": {
                    "operationId": "createUpload",
                    "requestBody": {
                        "required": true,
                        "content": {
                            "multipart/form-data": {
                                "schema": {"$ref": "#/components/schemas/UploadRequest"}
                            }
                        }
                    },
                    "responses": {"204": {"description": "Uploaded"}}
                }
            },
            "/uploads/compat": {
                "post": {
                    "operationId": "createUploadWithMultipartFilenames",
                    "responses": {"204": {"description": "Compatibility operation"}}
                }
            }
        },
        "components": {
            "schemas": {
                "Mode": {
                    "type": "string",
                    "enum": ["fast", "safe"]
                },
                "File": {
                    "type": "string",
                    "format": "binary"
                },
                "UploadRequest": {
                    "type": "object",
                    "required": ["labels", "file", "thumbnail"],
                    "properties": {
                        "labels": {
                            "type": "array",
                            "items": {"type": "string"}
                        },
                        "modes": {
                            "type": "array",
                            "items": {"$ref": "#/components/schemas/Mode"}
                        },
                        "file": {
                            "anyOf": [
                                {"$ref": "#/components/schemas/File"},
                                {"type": "null"}
                            ]
                        },
                        "thumbnail": {"$ref": "#/components/schemas/File"}
                    }
                }
            }
        }
    });

    let mut analyzer = SchemaAnalyzer::new(spec)?;
    let analysis = analyzer.analyze()?;
    let generator = CodeGenerator::new(GeneratorConfig {
        spec_path: PathBuf::from("fixture.json"),
        output_dir: PathBuf::from("target/multipart-fixture"),
        module_name: "fixture".to_string(),
        enable_async_client: true,
        ..Default::default()
    });
    let client = generator.generate_http_client(&analysis)?;

    assert!(
        !client.contains("must be binary or a scalar text field"),
        "{client}"
    );
    assert!(
        client.contains("form = form.text(\"labels\", item.to_string());"),
        "required string arrays must use repeated multipart fields: {client}"
    );
    assert!(
        client.contains("form = form.text(\"modes\", item.to_string());"),
        "enum arrays must use repeated multipart fields: {client}"
    );
    assert!(
        client.contains("pub async fn create_upload_with_multipart_filenames_2("),
        "the additive filename variant must be allocated around real operation names: {client}"
    );
    assert!(
        client.contains("pub async fn create_upload_with_multipart_filenames("),
        "the real operation must retain its historical name: {client}"
    );
    assert!(
        client.contains("multipart_filenames: &[(&str, &str)]"),
        "filename overrides must be request-local rather than client state: {client}"
    );
    assert!(
        client.contains("*field == \"file\"") && client.contains("*field == \"thumbnail\""),
        "each binary field must resolve its own filename override: {client}"
    );
    let base_start = client
        .find("pub async fn create_upload(")
        .expect("base multipart method");
    let variant_start = client
        .find("pub async fn create_upload_with_multipart_filenames_2(")
        .expect("allocated filename variant");
    let base_method = &client[base_start..variant_start];
    assert!(
        base_method.contains("reqwest::multipart::Part::bytes(value.to_vec())"),
        "the historical multipart method must still emit raw byte parts: {base_method}"
    );
    assert!(
        !base_method.contains(".file_name("),
        "the additive filename API must not change historical multipart wire semantics: {base_method}"
    );
    assert!(
        client[variant_start..].contains("part.file_name((*filename).to_string())"),
        "the additive method must apply only explicit per-field filename overrides: {client}"
    );
    Ok(())
}
''')
