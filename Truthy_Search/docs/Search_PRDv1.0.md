我的需求是：
    1、做一个已知接口请求与获取响应中的字段，我通过接口的方式，大量的请求接口，返回响应后，去拿到接口响应的数据。
    2、我接口流程：CreateIntentTask-GetTask-ListTaskCandidates-GetTaskCandidateDetail
    3、我会提供CreateIntentTask的请求参数（会很多，比如用json格式表示），然后提取GetTaskCandidateDetail的响应中的字段。
    4、在CreateIntentTask请求的字段params中，我会提供具体的clues与additional_details
    5、我需要获取GetTaskCandidateDetail的响应中的字段，responses.data中的ui_sections里面 的字段
    6、我可能一次性准备了100个或者更多的clues与additional_details，我需要批量请求，获取所有的ui_sections字段
    7、请求字段的准备格式你觉得是json还是csv格式，更方便？然后我要提取的字段也是json格式还是csv格式？会不会请求与响应先用json格式，然后最后在全部转成csv格式？因为我是要做成报告与分析的





    以下是这4个接口的请求参数与响应字段的例子：
1、CreateIntentTask创建并启动 3.0 线索搜索任务请求与响应

CreateIntentTask_request = {
    "comm": {
        "auth_token": "{{access_token}}",
        "device_id": "{{device_id}}",
        "user_id": "user_f0540a1f9771c7aa1f50a5cc",
        "client_request_id": "crid_{{time}}111",
        "platform": "'ios'",
        "app_version": "1.0.0",
        "locale": "zh-Hans-CN",
        "timezone": "UTC+08:00"
    },
    "requests": [
        {
            "id": "req_0",
            "service_name": "tool.people_insight.SearchService",
            "method_name": "CreateIntentTask",
            "params": {
                "client_request_id": "crid-search-{{time}}111",
                "match_strategy": "UNION",
                "clues": [
                    {
                        "type": "FULL_NAME",
                        "full_name_query": {
                            "full_name": "JOJO CCQQ MOCK"
                        }
                    },
                    {
                        "type": "LOCATION",
                        "location_query": {
                            "location": "us"
                        }
                    },
                    {
                        "type": "SOCIAL_LINK",
                        "social_link_query": {
                            "url": "https://www.linkedin.com/search/results/people/?keywords=John%20Smith%20photographer",
                            "platform_hint": "linkedin"
                        }
                    },
                    {
                        "type": "SOCIAL_LINK",
                        "social_link_query": {
                            "url": "https://x.com",
                            "platform_hint": "twitter"
                        }
                    },
                    {
                        "type": "PHOTO",
                        "photo_query": {
                            "media_asset_id": "{{media_asset_id}}",
                            "photo_type_hint": "face"
                        }
                    }
                ],
                "additional_details": [
                    {
                        "type": "PROFESSION",
                        "value": "aa"
                    },
                    {
                        "type": "EMPLOYER",
                        "value": "bb"
                    },
                    {
                        "type": "SCHOOL",
                        "value": "cc"
                    },
                    {
                        "type": "OTHER",
                        "value": "dd"
                    }
                ]
            }
        }
    ]
}

CreateIntentTask_response = {
    "code": 0,
    "message": "ok",
    "request_id": "gw_req_7677957cfe572b578799aabd6a900639",
    "trace_id": "trace_3cfa23a8306322c688e32fa336ebf86e",
    "responses": [
        {
            "id": "req_0",
            "success": true,
            "code": 0,
            "message": "ok",
            "data": {
                "accepted_query_type": "MULTI",
                "additional_details": [
                    {
                        "type": "PROFESSION",
                        "value": "aa"
                    },
                    {
                        "type": "EMPLOYER",
                        "value": "bb"
                    },
                    {
                        "type": "SCHOOL",
                        "value": "cc"
                    },
                    {
                        "type": "OTHER",
                        "value": "dd"
                    }
                ],
                "cache_hit": false,
                "can_start_real_search": true,
                "clue_types": [
                    "FULL_NAME",
                    "LOCATION",
                    "SOCIAL_LINK",
                    "SOCIAL_LINK",
                    "PHOTO"
                ],
                "entitlement_decision": "ALLOW",
                "expires_time": 1786850101758,
                "match_strategy": "UNION",
                "status": "QUEUED",
                "task_id": "task_cd520407e9d29ca4cc314d09"
            }
        }
    ]
}

2、GetTask轮询任务状态请求与响应

GetTask_request = {
    "comm": {
        "auth_token": "{{access_token}}",
        "device_id": "{{device_id}}",
        "user_id": "user_f0540a1f9771c7aa1f50a5cc",
        "client_request_id": "crid_{{time}}111",
        "platform": "'ios'",
        "app_version": "1.0.0",
        "locale": "zh-Hans-CN",
        "timezone": "UTC+08:00"
    },
    "requests": [
        {
            "id": "req_0",
            "service_name": "tool.people_insight.SearchService",
            "method_name": "GetTask",
            "params": {
                "task_id": "{{task_id}}"
            }
        }
        ]
    }

GetTask_response = {
    "code": 0,
    "message": "ok",
    "request_id": "gw_req_44b559bddb35f16459f8944b8ef68bb8",
    "trace_id": "trace_c570a119f752ccedde808a4ba8b55ffc",
    "responses": [
        {
            "id": "req_0",
            "success": true,
            "code": 0,
            "message": "ok",
            "data": {
                "cache_hit": false,
                "candidate_confidence_scores": [
                    27,
                    60
                ],
                "candidate_count": 2,
                "error_code": "",
                "failure_reason": "",
                "has_additional_clues": true,
                "is_initial_search": true,
                "no_result_reason": "",
                "progress": {
                    "display_message": "Report ready",
                    "display_percent": 100,
                    "stage": "report_ready"
                },
                "provider_execution": "REAL_PROVIDER",
                "provider_summary": {
                    "cache_hit": false,
                    "primary_provider": "people_data_labs",
                    "provider_execution": "REAL_PROVIDER",
                    "providers": [
                        "people_data_labs",
                        "searchapi_google_lens",
                        "llm_search",
                        "people_llm_primary",
                        "photo_aggregate"
                    ],
                    "public_sources": false,
                    "source_provider": "people_data_labs",
                    "source_providers": [
                        "people_data_labs",
                        "ebay",
                        "ikea",
                        "pamtonschnell machines",
                        "amazon.com",
                        "worthpoint",
                        "realtor.com",
                        "reddit",
                        "khomo gear",
                        "youtube",
                        "2strokeworld.net",
                        "llm_search",
                        "searchapi_google_lens",
                        "google help",
                        "zillow",
                        "visit canton",
                        "pinterest",
                        "bee namibia cars added a new photo. - bee namibia cars",
                        "yelp",
                        "github",
                        "magnific"
                    ]
                },
                "result_type": "multiple",
                "status": "SUCCEEDED",
                "task_id": "task_cd520407e9d29ca4cc314d09",
                "top_confidence_score": 27,
                "update_time": 1784258136071
            }
        }
    ]
}

3、ListTaskCandidates查询候选集列表请求与响应
ListTaskCandidates_request = {
    "comm": {
        "auth_token": "{{access_token}}",
        "device_id": "{{device_id}}",
        "user_id": "user_f0540a1f9771c7aa1f50a5cc",
        "client_request_id": "crid_{{time}}111",
        "platform": "'ios'",
        "app_version": "1.0.0",
        "locale": "zh-Hans-CN",
        "timezone": "UTC+08:00"
    },
    "requests": [
        {
            "id": "req_0",
            "service_name": "tool.people_insight.SearchService",
            "method_name": "ListTaskCandidates",
            "params": {
                "task_id": "{{task_id}}",
                "page": {
                    "page_size": 10,
                    "page_token": ""
                }
            }
        }
    ]
}

ListTaskCandidates_response = {
    "code": 0,
    "message": "ok",
    "request_id": "gw_req_6216afe09578b73b13bd2751d71d2bcc",
    "trace_id": "trace_dd4462e5ff38a9797897b890a4e08e33",
    "responses": [
        {
            "id": "req_0",
            "success": true,
            "code": 0,
            "message": "ok",
            "data": {
                "empty_reason": "",
                "items": [
                    {
                        "age": 0,
                        "avatar_url": "https://i.ebayimg.com/images/g/9EkAAOSwTj9lRF3r/s-l1200.jpg",
                        "candidate_id": "report_cadd7bf01ef64931746393d3_candidate_2",
                        "confidence_level": "MEDIUM",
                        "display_name": "Jojo Mock",
                        "education": "",
                        "evidence_count": 24,
                        "headline": "",
                        "is_best_match": false,
                        "is_top_result": true,
                        "jobs": [],
                        "location": "Vanuatu",
                        "match_reasons": [
                            "name"
                        ],
                        "match_score": 27,
                        "matched_clue_types": [
                            "FULL_NAME",
                            "LOCATION",
                            "SOCIAL_LINK",
                            "SOCIAL_LINK",
                            "PHOTO"
                        ],
                        "person_id": "pdl:BcLtbbxWL8sToMo9NvW3UQ_0000",
                        "primary_image": {
                            "priority": 2,
                            "reason": "provider_evidence_image",
                            "source": "provider_evidence",
                            "url": "https://i.ebayimg.com/images/g/9EkAAOSwTj9lRF3r/s-l1200.jpg"
                        },
                        "profile_url": "https://linkedin.com/in/jojo-mock-53107598",
                        "rank_breakdown": {
                            "data_completeness": 0.4,
                            "geo_relevance": 0,
                            "public_influence": 0,
                            "social_activity": 0,
                            "social_richness": 0.1667
                        },
                        "rank_score": 0.1817,
                        "rank_version": "candidate_ranking_v2",
                        "social_links": [
                            {
                                "platform": "linkedin",
                                "url": "https://linkedin.com/in/jojo-mock-53107598",
                                "username": "jojo-mock-53107598"
                            }
                        ],
                        "social_platforms": [
                            "linkedin"
                        ],
                        "source": "people_data_labs",
                        "source_provider": "people_data_labs"
                    },
                    {
                        "age": 0,
                        "avatar_url": "https://i.ebayimg.com/images/g/9EkAAOSwTj9lRF3r/s-l1200.jpg",
                        "candidate_id": "report_cadd7bf01ef64931746393d3_candidate_1",
                        "confidence_level": "MEDIUM",
                        "display_name": "JOJO CCQQ MOCK",
                        "education": "",
                        "evidence_count": 24,
                        "headline": "",
                        "is_best_match": false,
                        "is_top_result": false,
                        "jobs": [],
                        "location": "",
                        "match_reasons": [
                            "name",
                            "location"
                        ],
                        "match_score": 60,
                        "matched_clue_types": [
                            "FULL_NAME",
                            "LOCATION",
                            "SOCIAL_LINK",
                            "SOCIAL_LINK",
                            "PHOTO"
                        ],
                        "person_id": "candidate_001",
                        "primary_image": {
                            "priority": 2,
                            "reason": "provider_evidence_image",
                            "source": "provider_evidence",
                            "url": "https://i.ebayimg.com/images/g/9EkAAOSwTj9lRF3r/s-l1200.jpg"
                        },
                        "profile_url": "",
                        "rank_breakdown": {
                            "data_completeness": 0.1,
                            "geo_relevance": 0,
                            "public_influence": 0,
                            "social_activity": 0,
                            "social_richness": 0
                        },
                        "rank_score": 0.035,
                        "rank_version": "candidate_ranking_v2",
                        "social_links": [],
                        "social_platforms": [],
                        "source": "",
                        "source_provider": ""
                    }
                ],
                "next_page_token": "",
                "provider_summary": {
                    "cache_hit": false,
                    "primary_provider": "people_data_labs",
                    "provider_execution": "REAL_PROVIDER",
                    "providers": [
                        "people_data_labs",
                        "searchapi_google_lens",
                        "llm_search",
                        "people_llm_primary",
                        "photo_aggregate"
                    ],
                    "public_sources": false,
                    "source_provider": "people_data_labs",
                    "source_providers": [
                        "people_data_labs",
                        "ebay",
                        "ikea",
                        "pamtonschnell machines",
                        "amazon.com",
                        "worthpoint",
                        "realtor.com",
                        "reddit",
                        "khomo gear",
                        "youtube",
                        "2strokeworld.net",
                        "llm_search",
                        "searchapi_google_lens",
                        "google help",
                        "zillow",
                        "visit canton",
                        "pinterest",
                        "bee namibia cars added a new photo. - bee namibia cars",
                        "yelp",
                        "github",
                        "magnific"
                    ]
                },
                "task_id": "task_cd520407e9d29ca4cc314d09",
                "update_time": 1784258136071
            }
        }
    ]
}

4、GetTaskCandidateDetail单个候选详情请求与响应

GetTaskCandidateDetail_request = {
    "comm": {
        "auth_token": "{{access_token}}",
        "device_id": "{{device_id}}",
        "user_id": "user_f0540a1f9771c7aa1f50a5cc",
        "client_request_id": "crid_{{time}}111",
        "platform": "'ios'",
        "app_version": "1.0.0",
        "locale": "zh-Hans-CN",
        "timezone": "UTC+08:00"
    },
    "requests": [
        {
            "id": "req_0",
            "service_name": "tool.people_insight.SearchService",
            "method_name": "GetTaskCandidateDetail",
            "params": {
                "task_id": "{{task_id}}",
                "candidate_id": "{{candidate_id_1}}"
            }
        }
    ]
}

GetTaskCandidateDetail_response = {

    "code": 0,
    "message": "ok",
    "request_id": "gw_req_9a6531688ddc8c287a46b32bdbdb8475",
    "trace_id": "trace_c0ee617480bcb571db82fe7b112a5591",
    "responses": [
        {
            "id": "req_0",
            "success": true,
            "code": 0,
            "message": "ok",
            "data": {
                "candidate": {
                    "age": 0,
                    "avatar_url": "https://i.ebayimg.com/images/g/9EkAAOSwTj9lRF3r/s-l1200.jpg",
                    "candidate_id": "report_cadd7bf01ef64931746393d3_candidate_2",
                    "confidence_level": "MEDIUM",
                    "display_name": "Jojo Mock",
                    "education": "",
                    "evidence_count": 24,
                    "headline": "",
                    "is_best_match": false,
                    "is_top_result": true,
                    "jobs": [],
                    "location": "Vanuatu",
                    "match_reasons": [
                        "name"
                    ],
                    "match_score": 27,
                    "matched_clue_types": [
                        "FULL_NAME",
                        "LOCATION",
                        "SOCIAL_LINK",
                        "SOCIAL_LINK",
                        "PHOTO"
                    ],
                    "person_id": "pdl:BcLtbbxWL8sToMo9NvW3UQ_0000",
                    "primary_image": {
                        "priority": 2,
                        "reason": "provider_evidence_image",
                        "source": "provider_evidence",
                        "url": "https://i.ebayimg.com/images/g/9EkAAOSwTj9lRF3r/s-l1200.jpg"
                    },
                    "profile_url": "https://linkedin.com/in/jojo-mock-53107598",
                    "rank_breakdown": {
                        "data_completeness": 0.4,
                        "geo_relevance": 0,
                        "public_influence": 0,
                        "social_activity": 0,
                        "social_richness": 0.1667
                    },
                    "rank_score": 0.1817,
                    "rank_version": "candidate_ranking_v2",
                    "social_links": [
                        {
                            "platform": "linkedin",
                            "url": "https://linkedin.com/in/jojo-mock-53107598",
                            "username": "jojo-mock-53107598"
                        }
                    ],
                    "social_platforms": [
                        "linkedin"
                    ],
                    "source": "people_data_labs",
                    "source_provider": "people_data_labs"
                },
                "candidate_id": "report_cadd7bf01ef64931746393d3_candidate_2",
                "disclaimers": [
                    "Full-name search is the primary identity anchor; photo search results are supporting public web evidence and should not be treated as face identification.",
                    "People search results combine multiple data providers and should be reviewed before relying on identity matches.",
                    "Results are based on provided clues and may not be fully verified.",
                    "Photo match is assumed from media asset ID, not directly confirmed.",
                    "No direct address or phone found; location is country-level only.",
                    "People Data Labs Identify may return multiple candidates; review match scores and matched fields before relying on a person match.",
                    "Photo search results combine reverse-image/source providers; they are supporting leads and do not identify a person by face.",
                    "Results are generated from SearchAPI Google Lens public web image matches and should be reviewed as source leads, not identity confirmation.",
                    "Google Lens-style reverse image search finds web references and visually similar images; it is not a face-identification API."
                ],
                "entitlement_decision": "ALLOW",
                "evidence": [
                    {
                        "display_name": "Jojo Mock",
                        "matched_on": [
                            "name"
                        ],
                        "person_id": "pdl:BcLtbbxWL8sToMo9NvW3UQ_0000",
                        "provider": "people_data_labs",
                        "provider_person_id": "BcLtbbxWL8sToMo9NvW3UQ_0000",
                        "subject_profile_url": "linkedin.com/in/jojo-mock-53107598",
                        "type": "pdl_matched_on"
                    },
                    {
                        "display_name": "Jojo Mock",
                        "field": "linkedin_url",
                        "person_id": "pdl:BcLtbbxWL8sToMo9NvW3UQ_0000",
                        "provider": "people_data_labs",
                        "provider_person_id": "BcLtbbxWL8sToMo9NvW3UQ_0000",
                        "subject_profile_url": "linkedin.com/in/jojo-mock-53107598",
                        "type": "pdl_profile_url",
                        "url": "linkedin.com/in/jojo-mock-53107598"
                    },
                    {
                        "currency": "USD",
                        "extracted_price": 28,
                        "image_url": "https://i.ebayimg.com/images/g/9EkAAOSwTj9lRF3r/s-l1200.jpg",
                        "position": 1,
                        "price": "$28*",
                        "provider": "searchapi_google_lens",
                        "source": "eBay",
                        "stock_information": "In stock",
                        "thumbnail": "https://encrypted-tbn1.gstatic.com/images?q=tbn:ANd9GcTKs3zNbY4E_LNQmAanZK6GvGING7eAVb4Y7pBp09z0Y75Rrei6",
                        "title": "Target Water Sensor Flow Switch 1/2 3/4 1 Inch Flow Sensor ...",
                        "type": "image_visual_match",
                        "url": "https://www.ebay.com/itm/296023308928"
                    }
                ],
                "person_id": "pdl:BcLtbbxWL8sToMo9NvW3UQ_0000",
                "social_accounts": [
                    {
                        "display_name": "Jojo Mock",
                        "person_id": "pdl:BcLtbbxWL8sToMo9NvW3UQ_0000",
                        "platform": "linkedin",
                        "profile_url": "https://linkedin.com/in/jojo-mock-53107598",
                        "source": "people_data_labs",
                        "url": "https://linkedin.com/in/jojo-mock-53107598",
                        "username": "jojo-mock-53107598"
                    }
                ],
                "task_id": "task_cd520407e9d29ca4cc314d09",
                "ui_sections": {
                    "insights": {
                        "data": {
                            "count": 0,
                            "items": []
                        },
                        "status": "empty"
                    },
                    "photos": {
                        "data": {
                            "authenticity_photos": [
                                {
                                    "image_url": "https://tool-srv-people-insight-1349591044.cos.na-siliconvalley.myqcloud.com/photo/user_f0540a1f9771c7aa1f50a5cc/20260717/media_39aa9699b30db86e3f4d518c.jpg?q-sign-algorithm=sha1&q-ak=IKIDKJG2b7cxlZM1TkplUfiEZieNvJVUGrIa&q-sign-time=1784258374%3B1784261974&q-key-time=1784258374%3B1784261974&q-header-list=host&q-url-param-list=&q-signature=d9296cd290d9b5f400d5a762ed5d09154216fb0f",
                                    "source_url": "https://www.ebay.com/itm/296023308928",
                                    "status": "found_online"
                                }
                            ],
                            "baseline_photo_url": "https://tool-srv-people-insight-1349591044.cos.na-siliconvalley.myqcloud.com/photo/user_f0540a1f9771c7aa1f50a5cc/20260717/media_39aa9699b30db86e3f4d518c.jpg?q-sign-algorithm=sha1&q-ak=IKIDKJG2b7cxlZM1TkplUfiEZieNvJVUGrIa&q-sign-time=1784258374%3B1784261974&q-key-time=1784258374%3B1784261974&q-header-list=host&q-url-param-list=&q-signature=d9296cd290d9b5f400d5a762ed5d09154216fb0f",
                            "identity_match_rate": 0,
                            "match_photos": []
                        },
                        "status": "data"
                    },
                    "profile": {
                        "data": {
                            "sections": [
                                {
                                    "items": [
                                        {
                                            "label": "Full Name",
                                            "value": "Jojo Mock"
                                        },
                                        {
                                            "label": "Location",
                                            "value": "Vanuatu"
                                        },
                                        {
                                            "label": "Profile URL",
                                            "value": "https://linkedin.com/in/jojo-mock-53107598"
                                        }
                                    ],
                                    "title": "Identity"
                                },
                                {
                                    "items": [],
                                    "title": "Career"
                                },
                                {
                                    "items": [],
                                    "title": "Background"
                                }
                            ]
                        },
                        "status": "data"
                    },
                    "social": {
                        "data": {
                            "private_accounts": [],
                            "profiles": [
                                {
                                    "display_handle": "jojo-mock-53107598",
                                    "platform": "linkedin",
                                    "url": "https://linkedin.com/in/jojo-mock-53107598",
                                    "username": "jojo-mock-53107598"
                                }
                            ]
                        },
                        "status": "data"
                    },
                    "summary": {
                        "data": {
                            "age": null,
                            "avatar_url": "https://i.ebayimg.com/images/g/9EkAAOSwTj9lRF3r/s-l1200.jpg",
                            "candidate_id": "report_cadd7bf01ef64931746393d3_candidate_2",
                            "confidence_level": "MEDIUM",
                            "disclaimers": [
                                "Full-name search is the primary identity anchor; photo search results are supporting public web evidence and should not be treated as face identification.",
                                "People search results combine multiple data providers and should be reviewed before relying on identity matches.",
                                "Results are based on provided clues and may not be fully verified.",
                                "Photo match is assumed from media asset ID, not directly confirmed.",
                                "No direct address or phone found; location is country-level only.",
                                "People Data Labs Identify may return multiple candidates; review match scores and matched fields before relying on a person match.",
                                "Photo search results combine reverse-image/source providers; they are supporting leads and do not identify a person by face.",
                                "Results are generated from SearchAPI Google Lens public web image matches and should be reviewed as source leads, not identity confirmation.",
                                "Google Lens-style reverse image search finds web references and visually similar images; it is not a face-identification API."
                            ],
                            "display_name": "Jojo Mock",
                            "education": "",
                            "generate_time": 1784258136071,
                            "headline": "",
                            "is_best_match": false,
                            "is_top_result": true,
                            "jobs": null,
                            "location": "Vanuatu",
                            "match_reasons": [
                                "name"
                            ],
                            "match_score": 27,
                            "more_social_count": 0,
                            "person_id": "pdl:BcLtbbxWL8sToMo9NvW3UQ_0000",
                            "primary_image": {
                                "priority": 2,
                                "reason": "provider_evidence_image",
                                "source": "provider_evidence",
                                "url": "https://i.ebayimg.com/images/g/9EkAAOSwTj9lRF3r/s-l1200.jpg"
                            },
                            "profile_url": "https://linkedin.com/in/jojo-mock-53107598",
                            "report_expires_at": 1786850101758,
                            "social_platforms": [
                                "linkedin"
                            ]
                        },
                        "status": "data"
                    }
                },
                "update_time": 1784258136071
            }
        }
    ]
}
