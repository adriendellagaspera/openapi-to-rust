from pathlib import Path

client_path = Path("src/client_generator.rs")
client = client_path.read_text()
old = '''        let candidates = self.success_response_candidates(analysis, operation);
        let selected_response = candidates
            .iter()
            .find(|(_, response)| {
                Self::preferred_response_representation(response) == base.representation
            })
            .map(|(_, response)| *response);

        if let Some(response) = selected_response {
            for representation in response
                .representations
                .iter()
                .map(Self::response_representation_from_inventory)
            {
                if representation == base.representation
                    || call_shapes
                        .iter()
                        .any(|shape| shape.representation == representation)
                {
                    continue;
                }

                let statuses: Vec<String> = candidates
                    .iter()
                    .filter_map(|(status, candidate)| {
                        Self::response_has_representation(candidate, &representation)
                            .then_some((*status).to_string())
                    })
                    .collect();
                if statuses.is_empty() {
                    continue;
                }

                let preferred =
                    Self::preferred_alternate_method_name(base_method_name, &representation);
                let method_name = Self::allocate_name(&preferred, used_method_names);
                let shape = self.build_call_shape_plan(
                    analysis,
                    operation,
                    method_name,
                    representation,
                    statuses,
                );
                call_shapes.push(shape.clone());

                if matches!(
                    shape.representation,
                    ClientResponseRepresentation::BinaryBuffered { .. }
                ) {
                    self.push_binary_stream_shape(
                        analysis,
                        operation,
                        &shape,
                        used_method_names,
                        &mut call_shapes,
                    );
                }
            }
        }
'''
new = '''        let candidates = self.success_response_candidates(analysis, operation);
        let mut alternate_representations = Vec::new();
        for (_, response) in &candidates {
            for representation in response
                .representations
                .iter()
                .map(Self::response_representation_from_inventory)
            {
                if representation != base.representation
                    && !alternate_representations.contains(&representation)
                {
                    alternate_representations.push(representation);
                }
            }
        }

        for representation in alternate_representations {
            let statuses: Vec<String> = candidates
                .iter()
                .filter_map(|(status, candidate)| {
                    Self::response_has_representation(candidate, &representation)
                        .then_some((*status).to_string())
                })
                .collect();
            if statuses.is_empty() {
                continue;
            }

            let preferred =
                Self::preferred_alternate_method_name(base_method_name, &representation);
            let method_name = Self::allocate_name(&preferred, used_method_names);
            let shape = self.build_call_shape_plan(
                analysis,
                operation,
                method_name,
                representation,
                statuses,
            );
            call_shapes.push(shape.clone());

            if matches!(
                shape.representation,
                ClientResponseRepresentation::BinaryBuffered { .. }
            ) {
                self.push_binary_stream_shape(
                    analysis,
                    operation,
                    &shape,
                    used_method_names,
                    &mut call_shapes,
                );
            }
        }
'''
if old not in client:
    raise SystemExit("planner block not found")
client_path.write_text(client.replace(old, new, 1))

test_path = Path("tests/client_response_call_shapes_test.rs")
test = test_path.read_text()
needle = '''            "/reserved-stream-name": {
                "get": {
                    "operationId": "renderStream",
                    "responses": {
                        "200": {
                            "description": "reserve the preferred generated suffix",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/RenderResult"}
                                }
                            }
                        }
                    }
                }
            }
'''
replacement = needle + ''',
            "/status-split": {
                "post": {
                    "operationId": "statusSplit",
                    "responses": {
                        "200": {
                            "description": "buffered json",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/RenderResult"}
                                }
                            }
                        },
                        "201": {
                            "description": "event stream",
                            "content": {
                                "text/event-stream": {
                                    "schema": {"type": "string"}
                                }
                            }
                        }
                    }
                }
            }
'''
if needle not in test:
    raise SystemExit("fixture insertion point not found")
test = test.replace(needle, replacement, 1)
assertion_needle = '''    assert_eq!(sse.source_operation.method, "POST");
    assert_eq!(sse.source_operation.path, "/render");

    let client = generator.generate_http_client(&analysis)?;
'''
assertion_replacement = '''    assert_eq!(sse.source_operation.method, "POST");
    assert_eq!(sse.source_operation.path, "/render");

    let status_split: Vec<_> = plan
        .iter()
        .filter(|shape| shape.source_operation.operation_id == "statusSplit")
        .collect();
    assert_eq!(status_split.len(), 2, "{status_split:#?}");
    let status_split_sse = status_split
        .iter()
        .find(|shape| {
            matches!(
                &shape.representation,
                ClientResponseRepresentation::EventStream { media_type }
                    if media_type == "text/event-stream"
            )
        })
        .expect("cross-status SSE call shape");
    assert_eq!(status_split_sse.success_statuses, ["201"]);
    assert_eq!(status_split_sse.rust_method_name, "status_split_stream");

    let client = generator.generate_http_client(&analysis)?;
'''
if assertion_needle not in test:
    raise SystemExit("fixture assertion point not found")
test = test.replace(assertion_needle, assertion_replacement, 1)
method_needle = '''        "pub async fn render_stream_2(",
    ] {
'''
method_replacement = '''        "pub async fn render_stream_2(",
        "pub async fn status_split_stream(",
    ] {
'''
if method_needle not in test:
    raise SystemExit("method assertion point not found")
test = test.replace(method_needle, method_replacement, 1)
test_path.write_text(test)
