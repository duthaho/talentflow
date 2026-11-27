"""Frozen ADR-008 OpenAPI shapes. Keep in sync with docs/webhooks/openapi.yaml.

Handlers validate requests; these shared response shapes also drive the DUTH-141 client.
"""

import copy

CONTRACT = {
    "paths": {
        "/v1/webhook-event-types": {
            "get": {
                "tags": ["webhooks"],
                "operationId": "listWebhookEventTypes",
                "summary": "List subscribable event types",
                "description": "Catalog types whose AsyncAPI entry "
                "has `x-talentflow.webhook = true`.",
                "responses": {
                    "200": {
                        "description": "Event types.",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["items"],
                                    "properties": {
                                        "items": {
                                            "type": "array",
                                            "items": {
                                                "$ref": "#/components/schemas/WebhookEventType"
                                            },
                                        }
                                    },
                                }
                            }
                        },
                    },
                    "401": {"$ref": "#/components/responses/Unauthorized"},
                    "403": {"$ref": "#/components/responses/Forbidden"},
                },
            }
        },
        "/v1/webhook-endpoints": {
            "get": {
                "tags": ["webhooks"],
                "operationId": "listWebhookEndpoints",
                "summary": "List webhook endpoints",
                "parameters": [
                    {
                        "name": "status",
                        "in": "query",
                        "schema": {"$ref": "#/components/schemas/EndpointStatus"},
                    },
                    {"$ref": "#/components/parameters/Cursor"},
                    {"$ref": "#/components/parameters/Limit"},
                ],
                "responses": {
                    "200": {
                        "description": "One page of "
                        "endpoints, "
                        "newest first. "
                        "Deleted "
                        "endpoints are "
                        "never listed.",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["items", "next_cursor"],
                                    "properties": {
                                        "items": {
                                            "type": "array",
                                            "items": {
                                                "$ref": "#/components/schemas/WebhookEndpoint"
                                            },
                                        },
                                        "next_cursor": {"type": ["string", "null"]},
                                    },
                                }
                            }
                        },
                    },
                    "400": {"$ref": "#/components/responses/ValidationError"},
                    "401": {"$ref": "#/components/responses/Unauthorized"},
                    "403": {"$ref": "#/components/responses/Forbidden"},
                },
            },
            "post": {
                "tags": ["webhooks"],
                "operationId": "createWebhookEndpoint",
                "summary": "Register an endpoint and its subscriptions",
                "description": "Idempotency-Key is ignored: this "
                "response contains the signing "
                "secret. The secret is shown only in "
                "this response.",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/CreateWebhookEndpointRequest"}
                        }
                    },
                },
                "responses": {
                    "201": {
                        "description": "Endpoint created.",
                        "headers": {
                            "Location": {"$ref": "#/components/headers/Location"},
                            "ETag": {"$ref": "#/components/headers/ETag"},
                            "Cache-Control": {"$ref": "#/components/headers/NoStore"},
                        },
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/WebhookEndpointWithSecret"}
                            }
                        },
                    },
                    "401": {"$ref": "#/components/responses/Unauthorized"},
                    "403": {"$ref": "#/components/responses/Forbidden"},
                    "409": {
                        "description": "`conflict` "
                        "(URL already "
                        "registered) or "
                        "`webhook-endpoint-limit-reached` "
                        "(10 per "
                        "tenant).",
                        "content": {
                            "application/problem+json": {
                                "schema": {"$ref": "#/components/schemas/Problem"}
                            }
                        },
                    },
                    "422": {"$ref": "#/components/responses/UnprocessableUrlOrBody"},
                },
            },
        },
        "/v1/webhook-endpoints/{endpoint_id}": {
            "parameters": [{"$ref": "#/components/parameters/EndpointId"}],
            "get": {
                "tags": ["webhooks"],
                "operationId": "getWebhookEndpoint",
                "summary": "Get an endpoint",
                "responses": {
                    "200": {
                        "description": "The endpoint. The ETag is its quoted version.",
                        "headers": {"ETag": {"$ref": "#/components/headers/ETag"}},
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/WebhookEndpoint"}
                            }
                        },
                    },
                    "401": {"$ref": "#/components/responses/Unauthorized"},
                    "403": {"$ref": "#/components/responses/Forbidden"},
                    "404": {"$ref": "#/components/responses/NotFound"},
                },
            },
            "patch": {
                "tags": ["webhooks"],
                "operationId": "updateWebhookEndpoint",
                "summary": "Update URL, description, subscriptions or enabled state",
                "description": "Requires If-Match. "
                "Idempotency-Key is "
                "supported, and the "
                "raw If-Match header "
                "is part of its "
                "fingerprint "
                "(ADR-007). `enabled: "
                "false` cancels "
                "pending deliveries. "
                "`enabled: true` "
                "clears "
                "`disabled_reason` and "
                "the failure streak.",
                "parameters": [
                    {"$ref": "#/components/parameters/IfMatch"},
                    {"$ref": "#/components/parameters/IdempotencyKey"},
                ],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/UpdateWebhookEndpointRequest"}
                        }
                    },
                },
                "responses": {
                    "200": {
                        "description": "Updated endpoint.",
                        "headers": {"ETag": {"$ref": "#/components/headers/ETag"}},
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/WebhookEndpoint"}
                            }
                        },
                    },
                    "400": {"$ref": "#/components/responses/InvalidPrecondition"},
                    "401": {"$ref": "#/components/responses/Unauthorized"},
                    "403": {"$ref": "#/components/responses/Forbidden"},
                    "404": {"$ref": "#/components/responses/NotFound"},
                    "409": {
                        "description": "`conflict`: "
                        "another "
                        "endpoint "
                        "already "
                        "uses "
                        "this "
                        "URL, "
                        "or "
                        "an "
                        "Idempotency-Key "
                        "reservation "
                        "is "
                        "in "
                        "progress.",
                        "content": {
                            "application/problem+json": {
                                "schema": {"$ref": "#/components/schemas/Problem"}
                            }
                        },
                    },
                    "412": {"$ref": "#/components/responses/PreconditionFailed"},
                    "422": {"$ref": "#/components/responses/UnprocessableUrlOrBody"},
                    "428": {"$ref": "#/components/responses/PreconditionRequired"},
                },
            },
            "delete": {
                "tags": ["webhooks"],
                "operationId": "deleteWebhookEndpoint",
                "summary": "Delete an endpoint",
                "description": "Requires If-Match. "
                "Leaves a tombstone, "
                "destroys every "
                "secret's ciphertext "
                "and cancels pending "
                "deliveries. The "
                "delivery log stays "
                "readable through "
                "`GET "
                "/v1/webhook-deliveries/{id}` "
                "until retention "
                "purges it.",
                "parameters": [{"$ref": "#/components/parameters/IfMatch"}],
                "responses": {
                    "204": {"description": "Deleted."},
                    "400": {"$ref": "#/components/responses/InvalidPrecondition"},
                    "401": {"$ref": "#/components/responses/Unauthorized"},
                    "403": {"$ref": "#/components/responses/Forbidden"},
                    "404": {"$ref": "#/components/responses/NotFound"},
                    "412": {"$ref": "#/components/responses/PreconditionFailed"},
                    "428": {"$ref": "#/components/responses/PreconditionRequired"},
                },
            },
        },
        "/v1/webhook-endpoints/{endpoint_id}/secret-rotations": {
            "parameters": [{"$ref": "#/components/parameters/EndpointId"}],
            "post": {
                "tags": ["webhooks"],
                "operationId": "rotateWebhookSecret",
                "summary": "Rotate the signing secret",
                "description": "Requires "
                "If-Match "
                "with "
                "a "
                "concrete "
                "version. "
                "A "
                "lone "
                "`*` "
                "returns "
                "400 "
                "`invalid-precondition`, "
                "because "
                "a "
                "wildcard "
                "would "
                "let a "
                "retried "
                "request "
                "rotate "
                "twice. "
                "Idempotency-Key "
                "is "
                "ignored "
                "because "
                "the "
                "response "
                "contains "
                "the "
                "new "
                "secret, "
                "so "
                "If-Match "
                "is "
                "what "
                "stops "
                "a "
                "double "
                "rotation. "
                "The "
                "current "
                "secret "
                "becomes "
                "`previous` "
                "until "
                "`grace_period_seconds` "
                "passes, "
                "and "
                "both "
                "sign "
                "meanwhile. "
                "An "
                "older "
                "`previous` "
                "expires "
                "at "
                "once.",
                "parameters": [{"$ref": "#/components/parameters/IfMatchNoWildcard"}],
                "requestBody": {
                    "required": False,
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/RotateSecretRequest"}
                        }
                    },
                },
                "responses": {
                    "201": {
                        "description": "New secret created.",
                        "headers": {
                            "ETag": {"$ref": "#/components/headers/ETag"},
                            "Cache-Control": {"$ref": "#/components/headers/NoStore"},
                        },
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/SecretRotationResponse"}
                            }
                        },
                    },
                    "400": {"$ref": "#/components/responses/InvalidPrecondition"},
                    "401": {"$ref": "#/components/responses/Unauthorized"},
                    "403": {"$ref": "#/components/responses/Forbidden"},
                    "404": {"$ref": "#/components/responses/NotFound"},
                    "412": {"$ref": "#/components/responses/PreconditionFailed"},
                    "422": {"$ref": "#/components/responses/UnprocessableUrlOrBody"},
                    "428": {"$ref": "#/components/responses/PreconditionRequired"},
                },
            },
        },
        "/v1/webhook-endpoints/{endpoint_id}/deliveries": {
            "parameters": [{"$ref": "#/components/parameters/EndpointId"}],
            "get": {
                "tags": ["webhooks"],
                "operationId": "listWebhookDeliveries",
                "summary": "Delivery log for one endpoint",
                "parameters": [
                    {
                        "name": "status",
                        "in": "query",
                        "description": "Repeatable. Without it, all statuses are returned.",
                        "style": "form",
                        "explode": True,
                        "schema": {
                            "type": "array",
                            "items": {"$ref": "#/components/schemas/DeliveryStatus"},
                        },
                    },
                    {
                        "name": "event_type",
                        "in": "query",
                        "schema": {"$ref": "#/components/schemas/EventType"},
                    },
                    {
                        "name": "event_id",
                        "in": "query",
                        "schema": {"type": "string", "format": "uuid"},
                    },
                    {
                        "name": "created_from",
                        "in": "query",
                        "description": "Inclusive lower bound.",
                        "schema": {"type": "string", "format": "date-time"},
                    },
                    {
                        "name": "created_to",
                        "in": "query",
                        "description": "Exclusive upper bound.",
                        "schema": {"type": "string", "format": "date-time"},
                    },
                    {"$ref": "#/components/parameters/Cursor"},
                    {"$ref": "#/components/parameters/Limit"},
                ],
                "responses": {
                    "200": {
                        "description": "One "
                        "page "
                        "of "
                        "deliveries, "
                        "ordered "
                        "`created_at "
                        "DESC, "
                        "id "
                        "DESC`.",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["items", "next_cursor"],
                                    "properties": {
                                        "items": {
                                            "type": "array",
                                            "items": {
                                                "$ref": "#/components/schemas/WebhookDelivery"
                                            },
                                        },
                                        "next_cursor": {"type": ["string", "null"]},
                                    },
                                }
                            }
                        },
                    },
                    "400": {"$ref": "#/components/responses/ValidationError"},
                    "401": {"$ref": "#/components/responses/Unauthorized"},
                    "403": {"$ref": "#/components/responses/Forbidden"},
                    "404": {"$ref": "#/components/responses/NotFound"},
                },
            },
        },
        "/v1/webhook-deliveries/{delivery_id}": {
            "parameters": [{"$ref": "#/components/parameters/DeliveryId"}],
            "get": {
                "tags": ["webhooks"],
                "operationId": "getWebhookDelivery",
                "summary": "One delivery with its attempts",
                "responses": {
                    "200": {
                        "description": "The delivery.",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/WebhookDeliveryDetail"}
                            }
                        },
                    },
                    "401": {"$ref": "#/components/responses/Unauthorized"},
                    "403": {"$ref": "#/components/responses/Forbidden"},
                    "404": {"$ref": "#/components/responses/NotFound"},
                },
            },
        },
        "/v1/webhook-deliveries/{delivery_id}/redeliveries": {
            "parameters": [{"$ref": "#/components/parameters/DeliveryId"}],
            "post": {
                "tags": ["webhooks"],
                "operationId": "redeliverWebhook",
                "summary": "Redeliver an event to the same endpoint",
                "description": "Creates "
                "a new "
                "delivery "
                "of the "
                "same "
                "event, "
                "sent "
                "with the "
                "same "
                "`webhook-id`, "
                "the "
                "current "
                "secrets "
                "and a "
                "fresh "
                "attempt "
                "counter. "
                "The "
                "original "
                "delivery "
                "is never "
                "changed. "
                "Allowed "
                "only "
                "when the "
                "original "
                "is "
                "terminal "
                "and the "
                "endpoint "
                "is "
                "enabled. "
                "Idempotency-Key "
                "is "
                "supported.",
                "parameters": [{"$ref": "#/components/parameters/IdempotencyKey"}],
                "responses": {
                    "202": {
                        "description": "The new delivery, queued for an immediate first attempt.",
                        "headers": {"Location": {"$ref": "#/components/headers/Location"}},
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/WebhookDelivery"}
                            }
                        },
                    },
                    "400": {"$ref": "#/components/responses/ValidationError"},
                    "401": {"$ref": "#/components/responses/Unauthorized"},
                    "403": {"$ref": "#/components/responses/Forbidden"},
                    "404": {"$ref": "#/components/responses/NotFound"},
                    "409": {
                        "description": "`delivery-not-redeliverable` "
                        "(the "
                        "original "
                        "is "
                        "not "
                        "terminal, "
                        "the "
                        "endpoint "
                        "is "
                        "not "
                        "enabled, "
                        "or "
                        "this "
                        "event "
                        "already "
                        "has "
                        "a "
                        "pending "
                        "delivery "
                        "to "
                        "this "
                        "endpoint), "
                        "or "
                        "`conflict` "
                        "while "
                        "an "
                        "Idempotency-Key "
                        "reservation "
                        "is "
                        "in "
                        "progress.",
                        "content": {
                            "application/problem+json": {
                                "schema": {"$ref": "#/components/schemas/Problem"}
                            }
                        },
                    },
                    "422": {
                        "description": "The Idempotency-Key was reused with a different request.",
                        "content": {
                            "application/problem+json": {
                                "schema": {"$ref": "#/components/schemas/Problem"}
                            }
                        },
                    },
                },
            },
        },
    },
    "components": {
        "securitySchemes": {
            "bearerAuth": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "JWT",
                "description": "Keycloak access token. The web "
                "app calls the API through its "
                "BFF session (ADR 004).",
            }
        },
        "parameters": {
            "EndpointId": {
                "name": "endpoint_id",
                "in": "path",
                "required": True,
                "schema": {"type": "string", "format": "uuid"},
            },
            "DeliveryId": {
                "name": "delivery_id",
                "in": "path",
                "required": True,
                "schema": {"type": "string", "format": "uuid"},
            },
            "Cursor": {
                "name": "cursor",
                "in": "query",
                "description": "Opaque cursor taken from `next_cursor`.",
                "schema": {"type": "string", "maxLength": 512},
            },
            "Limit": {
                "name": "limit",
                "in": "query",
                "schema": {"type": "integer", "minimum": 1, "maximum": 100, "default": 25},
            },
            "IfMatch": {
                "name": "If-Match",
                "in": "header",
                "required": True,
                "description": "Strong quoted version from the "
                "endpoint's ETag, a comma-separated list "
                "of tags, or `*` (ADR-007).",
                "schema": {"type": "string"},
                "example": '"3"',
            },
            "IfMatchNoWildcard": {
                "name": "If-Match",
                "in": "header",
                "required": True,
                "description": "Strong quoted version from "
                "the endpoint's ETag, or a "
                "comma-separated list of tags. "
                "A lone `*` is rejected with "
                "400 `invalid-precondition`.",
                "schema": {"type": "string", "not": {"const": "*"}},
                "example": '"3"',
            },
            "IdempotencyKey": {
                "name": "Idempotency-Key",
                "in": "header",
                "required": False,
                "description": "1–255 visible ASCII characters (ADR-005).",
                "schema": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 255,
                    "pattern": "^[\\x21-\\x7E]+$",
                },
            },
        },
        "headers": {
            "ETag": {
                "description": "Strong ETag, the quoted endpoint version.",
                "schema": {"type": "string"},
                "example": '"1"',
            },
            "Location": {"schema": {"type": "string", "format": "uri-reference"}},
            "NoStore": {"schema": {"type": "string", "const": "private, no-store"}},
        },
        "responses": {
            "Unauthorized": {
                "description": "`unauthorized`",
                "content": {
                    "application/problem+json": {"schema": {"$ref": "#/components/schemas/Problem"}}
                },
            },
            "Forbidden": {
                "description": "`forbidden`: the caller lacks `webhook:manage`.",
                "content": {
                    "application/problem+json": {"schema": {"$ref": "#/components/schemas/Problem"}}
                },
            },
            "NotFound": {
                "description": "`not-found`: the resource is missing, "
                "deleted, or belongs to another tenant.",
                "content": {
                    "application/problem+json": {"schema": {"$ref": "#/components/schemas/Problem"}}
                },
            },
            "ValidationError": {
                "description": "`validation-error` for a malformed query parameter or cursor.",
                "content": {
                    "application/problem+json": {"schema": {"$ref": "#/components/schemas/Problem"}}
                },
            },
            "UnprocessableUrlOrBody": {
                "description": "`webhook-url-not-allowed` "
                "(pointer `/url`; the "
                "detail names the broken "
                "rule, never the resolved "
                "address), "
                "`validation-error` (for "
                "example pointer "
                "`/event_types/0` for an "
                "unknown type), or an "
                "Idempotency-Key reused "
                "with a different request.",
                "content": {
                    "application/problem+json": {"schema": {"$ref": "#/components/schemas/Problem"}}
                },
            },
            "InvalidPrecondition": {
                "description": "`invalid-precondition`: "
                "malformed or weak If-Match, "
                "or a malformed "
                "Idempotency-Key "
                "(`validation-error`).",
                "content": {
                    "application/problem+json": {"schema": {"$ref": "#/components/schemas/Problem"}}
                },
            },
            "PreconditionFailed": {
                "description": "`precondition-failed`. The "
                "response carries the current "
                "ETag and `current_version`.",
                "headers": {"ETag": {"$ref": "#/components/headers/ETag"}},
                "content": {
                    "application/problem+json": {"schema": {"$ref": "#/components/schemas/Problem"}}
                },
            },
            "PreconditionRequired": {
                "description": "`precondition-required`: If-Match is missing.",
                "headers": {"Cache-Control": {"$ref": "#/components/headers/NoStore"}},
                "content": {
                    "application/problem+json": {"schema": {"$ref": "#/components/schemas/Problem"}}
                },
            },
        },
        "schemas": {
            "Problem": {
                "type": "object",
                "description": "RFC 9457 Problem Details, as described in `docs/api-errors.md`.",
                "required": ["type", "title", "status", "detail", "instance", "correlation_id"],
                "properties": {
                    "type": {"type": "string", "format": "uri"},
                    "title": {"type": "string"},
                    "status": {"type": "integer"},
                    "detail": {"type": "string"},
                    "instance": {"type": "string"},
                    "correlation_id": {"type": "string"},
                    "current_version": {"type": "integer"},
                    "errors": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["pointer", "detail"],
                            "properties": {
                                "pointer": {"type": "string"},
                                "detail": {"type": "string"},
                            },
                        },
                    },
                },
            },
            "EventType": {
                "type": "string",
                "description": "A catalog type with "
                "`x-talentflow.webhook = true` in "
                "`docs/events/asyncapi.yaml`.",
                "enum": [
                    "candidate_case.created.v1",
                    "candidate_case.stage_changed.v1",
                    "candidate_case.erased.v1",
                    "interview.scheduled.v1",
                    "offer.created.v1",
                ],
            },
            "WebhookEventType": {
                "type": "object",
                "required": ["type", "status", "description"],
                "properties": {
                    "type": {"$ref": "#/components/schemas/EventType"},
                    "status": {
                        "type": "string",
                        "enum": ["active", "planned", "reserved", "deprecated"],
                        "description": "Catalog "
                        "status. "
                        "`reserved` "
                        "types "
                        "can be "
                        "subscribed "
                        "to; "
                        "they "
                        "start "
                        "flowing "
                        "when "
                        "their "
                        "publisher "
                        "ships.",
                    },
                    "description": {"type": "string"},
                },
            },
            "EndpointStatus": {"type": "string", "enum": ["enabled", "disabled"]},
            "DisabledReason": {"type": "string", "enum": ["manual", "failing", "gone"]},
            "WebhookUrl": {
                "type": "string",
                "format": "uri",
                "maxLength": 2048,
                "description": "Absolute `https` URL (`http` only when "
                "`WEBHOOK_ALLOW_HTTP` is set, which is "
                "never in production). No userinfo or "
                "fragment. Ports 443/8443 (https) or "
                "80/8080 (http). Every resolved address "
                "must be public (ADR-008 §4).",
                "examples": ["https://hooks.example.com/talentflow?token=abc"],
            },
            "EventTypeList": {
                "type": "array",
                "minItems": 1,
                "maxItems": 20,
                "uniqueItems": True,
                "items": {"$ref": "#/components/schemas/EventType"},
            },
            "Description": {
                "type": ["string", "null"],
                "maxLength": 200,
                "description": "No control characters.",
            },
            "CreateWebhookEndpointRequest": {
                "type": "object",
                "additionalProperties": False,
                "required": ["url", "event_types"],
                "properties": {
                    "url": {"$ref": "#/components/schemas/WebhookUrl"},
                    "description": {"$ref": "#/components/schemas/Description"},
                    "event_types": {"$ref": "#/components/schemas/EventTypeList"},
                    "enabled": {"type": "boolean", "default": True},
                },
            },
            "UpdateWebhookEndpointRequest": {
                "type": "object",
                "additionalProperties": False,
                "minProperties": 1,
                "description": "Partial update. "
                "`event_types` "
                "replaces the whole "
                "set. A new `url` "
                "applies to the next "
                "attempt of every "
                "pending delivery, "
                "retries included "
                "(ADR-008 §5).",
                "properties": {
                    "url": {"$ref": "#/components/schemas/WebhookUrl"},
                    "description": {"$ref": "#/components/schemas/Description"},
                    "event_types": {"$ref": "#/components/schemas/EventTypeList"},
                    "enabled": {"type": "boolean"},
                },
            },
            "RotateSecretRequest": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "grace_period_seconds": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 604800,
                        "default": 86400,
                        "description": "How "
                        "long "
                        "the "
                        "old "
                        "secret "
                        "keeps "
                        "signing. "
                        "0 "
                        "expires "
                        "it "
                        "immediately "
                        "(use "
                        "this "
                        "after "
                        "a "
                        "leak).",
                    }
                },
            },
            "SecretMetadata": {
                "type": "object",
                "required": ["id", "status", "created_at", "expires_at"],
                "properties": {
                    "id": {"type": "string", "format": "uuid"},
                    "status": {"type": "string", "enum": ["current", "previous"]},
                    "created_at": {"type": "string", "format": "date-time"},
                    "expires_at": {
                        "type": ["string", "null"],
                        "format": "date-time",
                        "description": "Set only on `previous`.",
                    },
                },
            },
            "PlaintextSecret": {
                "type": "object",
                "required": ["id", "value"],
                "properties": {
                    "id": {"type": "string", "format": "uuid"},
                    "value": {
                        "type": "string",
                        "pattern": "^whsec_[A-Za-z0-9+/]{43}=$",
                        "description": "Shown only once. Store it in the receiver's secret store.",
                        "examples": ["whsec_AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8="],
                    },
                },
            },
            "WebhookEndpoint": {
                "type": "object",
                "required": [
                    "id",
                    "url",
                    "description",
                    "status",
                    "disabled_reason",
                    "event_types",
                    "secrets",
                    "consecutive_failures",
                    "failure_streak_started_at",
                    "version",
                    "created_at",
                    "updated_at",
                ],
                "properties": {
                    "id": {"type": "string", "format": "uuid"},
                    "url": {"$ref": "#/components/schemas/WebhookUrl"},
                    "description": {"$ref": "#/components/schemas/Description"},
                    "status": {"$ref": "#/components/schemas/EndpointStatus"},
                    "disabled_reason": {
                        "oneOf": [{"$ref": "#/components/schemas/DisabledReason"}, {"type": "null"}]
                    },
                    "event_types": {
                        "type": "array",
                        "items": {"$ref": "#/components/schemas/EventType"},
                    },
                    "secrets": {
                        "type": "array",
                        "maxItems": 2,
                        "description": "Metadata only. The secret value is never returned here.",
                        "items": {"$ref": "#/components/schemas/SecretMetadata"},
                    },
                    "consecutive_failures": {"type": "integer", "minimum": 0},
                    "failure_streak_started_at": {
                        "type": ["string", "null"],
                        "format": "date-time",
                    },
                    "version": {"type": "integer", "minimum": 1},
                    "created_at": {"type": "string", "format": "date-time"},
                    "updated_at": {"type": "string", "format": "date-time"},
                },
            },
            "WebhookEndpointWithSecret": {
                "allOf": [
                    {"$ref": "#/components/schemas/WebhookEndpoint"},
                    {
                        "type": "object",
                        "required": ["secret"],
                        "properties": {"secret": {"$ref": "#/components/schemas/PlaintextSecret"}},
                    },
                ]
            },
            "SecretRotationResponse": {
                "type": "object",
                "required": ["endpoint", "secret", "previous_secret_expires_at"],
                "properties": {
                    "endpoint": {"$ref": "#/components/schemas/WebhookEndpoint"},
                    "secret": {"$ref": "#/components/schemas/PlaintextSecret"},
                    "previous_secret_expires_at": {
                        "type": "string",
                        "format": "date-time",
                        "description": "When "
                        "the "
                        "replaced "
                        "secret "
                        "stops "
                        "signing. "
                        "Equals "
                        "the "
                        "request "
                        "time "
                        "when "
                        "the "
                        "grace "
                        "period "
                        "is "
                        "0.",
                    },
                },
            },
            "DeliveryStatus": {
                "type": "string",
                "enum": ["pending", "succeeded", "dead_lettered", "cancelled"],
            },
            "AttemptErrorCode": {
                "type": "string",
                "enum": [
                    "http_status",
                    "redirect",
                    "timeout",
                    "dns_error",
                    "connect_error",
                    "tls_error",
                    "blocked_address",
                    "invalid_url",
                    "response_too_large",
                ],
            },
            "WebhookDelivery": {
                "type": "object",
                "required": [
                    "id",
                    "endpoint_id",
                    "event_id",
                    "event_type",
                    "kind",
                    "status",
                    "attempt_count",
                    "max_attempts",
                    "next_attempt_at",
                    "last_attempt_at",
                    "last_status_code",
                    "last_error_code",
                    "redelivery_of_id",
                    "requested_by",
                    "created_at",
                    "completed_at",
                ],
                "properties": {
                    "id": {"type": "string", "format": "uuid"},
                    "endpoint_id": {"type": "string", "format": "uuid"},
                    "event_id": {
                        "type": "string",
                        "format": "uuid",
                        "description": "The CloudEvents id, sent as `webhook-id`.",
                    },
                    "event_type": {"$ref": "#/components/schemas/EventType"},
                    "kind": {
                        "type": "string",
                        "enum": ["fanout", "redelivery"],
                        "description": "Set on "
                        "creation "
                        "and never "
                        "changes. "
                        "`redelivery` "
                        "rows were "
                        "created by "
                        "an admin "
                        "redelivery.",
                    },
                    "status": {"$ref": "#/components/schemas/DeliveryStatus"},
                    "attempt_count": {"type": "integer", "minimum": 0, "maximum": 8},
                    "max_attempts": {"type": "integer", "const": 8},
                    "next_attempt_at": {"type": ["string", "null"], "format": "date-time"},
                    "last_attempt_at": {"type": ["string", "null"], "format": "date-time"},
                    "last_status_code": {"type": ["integer", "null"]},
                    "last_error_code": {
                        "oneOf": [
                            {"$ref": "#/components/schemas/AttemptErrorCode"},
                            {"type": "null"},
                        ]
                    },
                    "redelivery_of_id": {
                        "type": ["string", "null"],
                        "format": "uuid",
                        "description": "Lineage "
                        "of "
                        "a "
                        "`redelivery` "
                        "row. "
                        "It "
                        "becomes "
                        "null "
                        "once "
                        "retention "
                        "purges "
                        "the "
                        "original; "
                        "`kind` "
                        "still "
                        "identifies "
                        "the "
                        "row.",
                    },
                    "requested_by": {
                        "type": ["string", "null"],
                        "description": "Actor id for a manual redelivery.",
                    },
                    "created_at": {"type": "string", "format": "date-time"},
                    "completed_at": {"type": ["string", "null"], "format": "date-time"},
                },
            },
            "WebhookDeliveryAttempt": {
                "type": "object",
                "required": [
                    "attempt_number",
                    "started_at",
                    "duration_ms",
                    "status_code",
                    "error_code",
                ],
                "description": "Receiver response bodies and headers are never stored.",
                "properties": {
                    "attempt_number": {"type": "integer", "minimum": 1, "maximum": 8},
                    "started_at": {"type": "string", "format": "date-time"},
                    "duration_ms": {"type": "integer", "minimum": 0},
                    "status_code": {"type": ["integer", "null"]},
                    "error_code": {
                        "oneOf": [
                            {"$ref": "#/components/schemas/AttemptErrorCode"},
                            {"type": "null"},
                        ]
                    },
                },
            },
            "WebhookDeliveryDetail": {
                "allOf": [
                    {"$ref": "#/components/schemas/WebhookDelivery"},
                    {
                        "type": "object",
                        "required": ["attempts"],
                        "properties": {
                            "attempts": {
                                "type": "array",
                                "items": {"$ref": "#/components/schemas/WebhookDeliveryAttempt"},
                            }
                        },
                    },
                ]
            },
            "CloudEvent": {
                "type": "object",
                "description": "The ADR 006 envelope. `data` is defined "
                "per type in "
                "`docs/events/asyncapi.yaml`.",
                "required": [
                    "specversion",
                    "id",
                    "source",
                    "type",
                    "time",
                    "datacontenttype",
                    "subject",
                    "tenantid",
                    "correlationid",
                    "causationid",
                    "data",
                ],
                "properties": {
                    "specversion": {"type": "string", "const": "1.0"},
                    "id": {"type": "string", "format": "uuid"},
                    "source": {"type": "string", "pattern": "^urn:talentflow:[a-z_]+$"},
                    "type": {"$ref": "#/components/schemas/EventType"},
                    "time": {"type": "string", "format": "date-time"},
                    "datacontenttype": {"type": "string", "const": "application/json"},
                    "subject": {"type": "string"},
                    "tenantid": {"type": "string"},
                    "correlationid": {"type": "string"},
                    "causationid": {"type": "string"},
                    "actorid": {"type": "string"},
                    "traceparent": {"type": "string"},
                    "data": {"type": "object"},
                },
            },
        },
    },
    "webhooks": {
        "talentflowEvent": {
            "post": {
                "tags": ["webhooks"],
                "operationId": "receiveTalentflowEvent",
                "security": [],
                "summary": "Outbound event request sent to a registered endpoint",
                "description": "One request per attempt. Signed content "
                'is `"{webhook-id}.{webhook-timestamp}." '
                "+ raw body`,\n"
                "HMAC-SHA256 with the decoded `whsec_` "
                "key, base64 encoded (Standard Webhooks "
                "`v1`).\n"
                "Receivers verify the raw bytes, reject "
                "timestamps more than 300 s away from "
                "their own\n"
                "clock, and deduplicate on `webhook-id`. "
                "A 2xx counts as success. Redirects are "
                "not followed.\n"
                "410 Gone disables the endpoint. Any "
                "other result is retried (ADR-008 §5).\n",
                "parameters": [
                    {
                        "name": "webhook-id",
                        "in": "header",
                        "required": True,
                        "description": "CloudEvents `id`. The "
                        "same value on every "
                        "retry and redelivery of "
                        "the event.",
                        "schema": {"type": "string", "format": "uuid"},
                    },
                    {
                        "name": "webhook-timestamp",
                        "in": "header",
                        "required": True,
                        "description": "Unix seconds when this attempt was signed.",
                        "schema": {"type": "string", "pattern": "^[0-9]{1,12}$"},
                    },
                    {
                        "name": "webhook-signature",
                        "in": "header",
                        "required": True,
                        "description": "Space-separated "
                        "`v1,<base64>` entries, "
                        "one per active secret: "
                        "current first, then "
                        "previous during a "
                        "rotation grace period.",
                        "schema": {
                            "type": "string",
                            "pattern": "^v1,[A-Za-z0-9+/]{43}=( v1,[A-Za-z0-9+/]{43}=)?$",
                        },
                        "example": "v1,tf0j4MFE0WB8v3pV96njh8f00nDy2gSfd7KprE+McKU=",
                    },
                    {
                        "name": "User-Agent",
                        "in": "header",
                        "required": True,
                        "schema": {"type": "string", "const": "TalentFlow-Webhooks/1"},
                    },
                ],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/cloudevents+json": {
                            "schema": {"$ref": "#/components/schemas/CloudEvent"},
                            "example": {
                                "specversion": "1.0",
                                "id": "0b7e1c9a-4f3d-4c55-9a52-3f1f6f3c2d10",
                                "source": "urn:talentflow:candidates",
                                "type": "candidate_case.stage_changed.v1",
                                "time": "2026-11-27T09:00:00Z",
                                "datacontenttype": "application/json",
                                "subject": "c-123",
                                "tenantid": "t-1",
                                "correlationid": "req-1",
                                "causationid": "req-1",
                                "data": {
                                    "candidate_case_id": "c-123",
                                    "from_stage": "screening",
                                    "to_stage": "interviewing",
                                    "version": 3,
                                },
                            },
                        }
                    },
                },
                "responses": {
                    "2XX": {
                        "description": "Accepted by the "
                        "receiver. The "
                        "body is discarded "
                        "after at most 64 "
                        "KiB."
                    },
                    "410": {
                        "description": "Gone. The "
                        "delivery is "
                        "dead-lettered and "
                        "the endpoint is "
                        "auto-disabled "
                        "(`gone`)."
                    },
                    "default": {
                        "description": "Failure. Retried on the ADR-008 schedule, up to 8 attempts."
                    },
                },
            }
        }
    },
}


def install_webhook_openapi(app):
    original = app.openapi

    def documented():
        schema = original()
        contract = copy.deepcopy(CONTRACT)
        for path, operations in contract["paths"].items():
            for method in operations:
                if method != "parameters" and method not in schema["paths"].get(path, {}):
                    raise RuntimeError("Webhook route is missing from the implementation")
        schema["paths"].update(contract["paths"])
        for name, values in contract["components"].items():
            schema["components"].setdefault(name, {}).update(values)
        schema["webhooks"] = contract["webhooks"]
        for path in contract["paths"]:
            for method, operation in schema["paths"][path].items():
                if method != "parameters":
                    operation["security"] = [{"bearerAuth": []}]
        return schema

    app.openapi = documented
