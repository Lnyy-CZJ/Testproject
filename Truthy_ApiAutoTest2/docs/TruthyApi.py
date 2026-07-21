
url = "http://gateway.spark-jam.top/gateway/invoke"
headers = {
   'Content-Type': 'application/json',
   'Accept': '*/*',
   'Host': 'gateway.spark-jam.top',
   'Connection': 'keep-alive'
}

# 1、创建匿名会话请求与响应
CreateAnonymousSession_request = {
   "comm": {
      "auth_token": "ef437f75-2731-4411-9011-0153b6f9727d",
      "device_id": "4LbBrznCBBQSMFrGag01u",
      "install_id": "install_36",
      "client_request_id": "crid_473",
      "trace_id": "trace_828",
      "platform": "'ios'",
      "app_version": "1.0.0",
      "locale": "US",
      "timezone": "1781775705713"
   },
   "requests": [
      {
         "id": "req_119",
         "service_name": "tool.identity.IdentityService",
         "method_name": "CreateAnonymousSession",
         "params": {
            "consent_policy_version": "2025-07-02"
         }
      }
   ]
}

CreateAnonymousSession_response = {
    "code": 0,
    "message": "ok",
    "request_id": "gw_req_60f3109bf0c86fbf86a35edbda8bb394",
    "trace_id": "trace_828",
    "responses": [
        {
            "id": "req_119",
            "success": true,
            "code": 0,
            "message": "ok",
            "data": {
                "access_token": "anon.dXNlcl9mZmJjMTM2OWJlMWMzNmI3YmQ2ZjEwODY.15d51a8b58c0df6d80ed48c7cf199166",
                "expires_time": 1784861172979,
                "is_new_user": false,
                "refresh_expires_time": 1799808372979,
                "refresh_token": "refresh.dagtWfT02_t_22-UCO4A_U2-g5olskmVuotDXuIvcgo",
                "user_id": "user_ffbc1369be1c36b7bd6f1086"
            }
        }
    ]
}


# 2、GetSubscriptionStatus查询订阅状态请求与响应

GetSubscriptionStatus_request = {
   "comm": {
      "auth_token": "anon.dXNlcl9mMDU0MGExZjk3NzFjN2FhMWY1MGE1Y2M.79356dabe6a0849464b70cd00abf2ccd",
      "device_id": "39d42779-2dcf-4759-9275-699eed5db695",
      "user_id": "user_f0540a1f9771c7aa1f50a5cc",
      "client_request_id": "crid_1784257153123111",
      "platform": "'ios'",
      "app_version": "1.0.0",
      "locale": "zh-Hans-CN",
      "timezone": "UTC+08:00"
   },
   "requests": [
      {
         "id": "req_0",
         "service_name": "tool.subscription.SubscriptionService",
         "method_name": "GetSubscriptionStatus",
         "params": {
            "product_code": "people_insight",
            "scenario": "search"
         }
      }
   ]
}

GetSubscriptionStatus_response = {
    "code": 0,
    "message": "ok",
    "request_id": "gw_req_60f3109bf0c86fbf86a35edbda8bb394",
    "trace_id": "trace_828",
    "responses": [
        {
            "id": "req_119",
            "success": true,
            "code": 0,
            "message": "ok",
            "data": {
                "access_token": "anon.dXNlcl9mZmJjMTM2OWJlMWMzNmI3YmQ2ZjEwODY.15d51a8b58c0df6d80ed48c7cf199166",
                "expires_time": 1784861172979,
                "is_new_user": false,
                "refresh_expires_time": 1799808372979,
                "refresh_token": "refresh.dagtWfT02_t_22-UCO4A_U2-g5olskmVuotDXuIvcgo",
                "user_id": "user_ffbc1369be1c36b7bd6f1086"
            }
        }
    ]
}

# 3、GetEntitlement获取当前订阅权益请求与响应
GetEntitlement_request = {
    "comm": {
        "auth_token": "anon.dXNlcl9mMDU0MGExZjk3NzFjN2FhMWY1MGE1Y2M.79356dabe6a0849464b70cd00abf2ccd",
        "device_id": "39d42779-2dcf-4759-9275-699eed5db695",
        "user_id": "user_f0540a1f9771c7aa1f50a5cc",
        "client_request_id": "crid_1784257648524111",
        "platform": "'ios'",
        "app_version": "1.0.0",
        "locale": "zh-Hans-CN",
        "timezone": "UTC+08:00"
    },
    "requests": [
        {
            "id": "req_0",
            "service_name": "tool.subscription.SubscriptionService",
            "method_name": "GetEntitlement",
            "params": {
                "product_code": "people_insight"
            }
        }
    ]
}

GetEntitlement_response = {
    "code": 0,
    "message": "ok",
    "request_id": "gw_req_019fd9355cced22fda5430055f19733f",
    "trace_id": "trace_6209adeec4da3f18673bce4bb8f970da",
    "responses": [
        {
            "id": "req_0",
            "success": true,
            "code": 0,
            "message": "ok",
            "data": {
                "can_start_search": true,
                "concurrency_remaining": 1,
                "decision": "ALLOW",
                "expires_time": 1814343683938,
                "plan_code": "basic",
                "product_code": "people_insight",
                "quota_remaining": 10,
                "subscription_status": "active",
                "vip_level": 1
            }
        }
    ]
}


#4、GetMediaUploadConfig 获取媒体上传配置请求与响应
GetMediaUploadConfig_request = {
  "comm": {
    "auth_token": "anon.dXNlcl9mMDU0MGExZjk3NzFjN2FhMWY1MGE1Y2M.79356dabe6a0849464b70cd00abf2ccd",
    "user_id": "user_f0540a1f9771c7aa1f50a5cc",
    "device_id": "39d42779-2dcf-4759-9275-699eed5db695",
    "client_request_id": "crid_1784087016436010",
    "platform": "ios",
    "app_version": "1.0.3",
    "locale": "zh-Hans-CN",
    "country": "CN",
    "timezone": "UTC+08:00"
  },
  "requests": [
    {
      "id": "req_0",
      "service_name": "tool.people_insight.MediaService",
      "method_name": "GetMediaUploadConfig",
      "params": {}
    }
  ]
}

GetMediaUploadConfig_response = {
    "code": 0,
    "message": "ok",
    "request_id": "gw_req_d9bb426a56b535461295b1cac7853a24",
    "trace_id": "trace_77ad63bd1f5b8298396cac1e82389f55",
    "responses": [
        {
            "id": "req_0",
            "success": true,
            "code": 0,
            "message": "ok",
            "data": {
                "allowed_content_types": [
                    "image/jpeg",
                    "image/png",
                    "image/webp"
                ],
                "asset_ttl_seconds": 2592000,
                "cache_expires_time": 1784344175158,
                "complete_retry": {
                    "initial_delay_ms": 500,
                    "max_attempts": 5,
                    "max_delay_ms": 5000
                },
                "config_cache_ttl_seconds": 86400,
                "config_version": "media_upload_v4_10mb",
                "face_detection_required": false,
                "max_size_bytes": 10000000,
                "recommended_jpeg_quality": 0.85,
                "recommended_max_height": 1600,
                "recommended_max_width": 1600,
                "strip_exif": true,
                "upload_url_ttl_seconds": 86400
            }
        }
    ]
}


#5、PrepareMediaUpload 准备媒体上传请求与响应

PrepareMediaUpload_request = {
  "comm": {
    "auth_token": "{{access_token}}",
    "user_id": "{{user_id}}",
    "device_id": "{{device_id}}",
    "client_request_id": "crid_photo_{{$date.millisecondsTimestamp}}746",
    "platform": "ios",
    "app_version": "1.0.3",
    "locale": "zh-Hans-CN",
    "country": "CN",
    "timezone": "UTC+08:00"
  },
  "requests": [
    {
      "id": "req_0",
      "service_name": "tool.people_insight.MediaService",
      "method_name": "PrepareMediaUpload",
      "params": {
        "client_request_id": "crid_photo_{{$date.millisecondsTimestamp}}746",
        "content_type": "image/jpeg",
        "size_bytes": 338532
      }
    }
  ]
}

PrepareMediaUpload_response = {
    "code": 0,
    "message": "ok",
    "request_id": "gw_req_10f4831890d1f34881809b0d3e908794",
    "trace_id": "trace_05df1e9ac2a2a573c59e291900d56e01",
    "responses": [
        {
            "id": "req_0",
            "success": true,
            "code": 0,
            "message": "ok",
            "data": {
                "content_type": "image/jpeg",
                "expires_time": 1784344251349,
                "max_size_bytes": 10000000,
                "media_asset_id": "media_39aa9699b30db86e3f4d518c",
                "size_bytes": 338532,
                "status": "pending",
                "upload_headers": {
                    "Content-Length": "338532",
                    "Content-Type": "image/jpeg"
                },
                "upload_method": "PUT",
                "upload_url": "https://tool-srv-people-insight-1349591044.cos.na-siliconvalley.myqcloud.com/photo/user_f0540a1f9771c7aa1f50a5cc/20260717/media_39aa9699b30db86e3f4d518c.jpg?q-sign-algorithm=sha1&q-ak=IKIDKJG2b7cxlZM1TkplUfiEZieNvJVUGrIa&q-sign-time=1784257851%3B1784344251&q-key-time=1784257851%3B1784344251&q-header-list=content-length%3Bcontent-type%3Bhost&q-url-param-list=&q-signature=76290a77bd0ba37485ef403c652a926a7f1d8034"
            }
        }
    ]
}

#5-1、PUT 上传图片至 COS（动态签名 URL）请求与响应
conn = http.client.HTTPSConnection("tool-srv-people-insight-1349591044.cos.na-siliconvalley.myqcloud.com")
payload = "<file contents here>"
headers = {
   'User-Agent': 'Apifox/1.0.0 (https://apifox.com)',
   'Content-Type': 'image/jpeg',
   'Accept': '*/*',
   'Host': 'tool-srv-people-insight-1349591044.cos.na-siliconvalley.myqcloud.com',
   'Connection': 'keep-alive'
}
conn.request("PUT", "/photo/user_f0540a1f9771c7aa1f50a5cc/20260717/media_39aa9699b30db86e3f4d518c.jpg?q-sign-algorithm=sha1&q-ak=IKIDKJG2b7cxlZM1TkplUfiEZieNvJVUGrIa&q-sign-time=1784257851%253B1784344251&q-key-time=1784257851%253B1784344251&q-header-list=content-length%253Bcontent-type%253Bhost&q-url-param-list=&q-signature=76290a77bd0ba37485ef403c652a926a7f1d8034", payload, headers)

#6、CompleteMediaUpload 完成媒体上传请求与响应

CompleteMediaUpload_request = {
  "comm": {
    "auth_token": "{{access_token}}",
    "user_id": "{{user_id}}",
    "device_id": "{{device_id}}",
    "client_request_id": "crid_photo_1784087019445746",
    "platform": "ios",
    "app_version": "1.0.3",
    "locale": "zh-Hans-CN",
    "country": "CN",
    "timezone": "UTC+08:00"
  },
  "requests": [
    {
      "id": "req_0",
      "service_name": "tool.people_insight.MediaService",
      "method_name": "CompleteMediaUpload",
      "params": {
        "media_asset_id": "{{media_asset_id}}"
      }
    }
  ]
}

CompleteMediaUpload_response = {
    "code": 0,
    "message": "ok",
    "request_id": "gw_req_0b2d19931848a8cb59dc0cae43988a96",
    "trace_id": "trace_ab4f425e19cfdb34e5004fb5467eac24",
    "responses": [
        {
            "id": "req_0",
            "success": true,
            "code": 0,
            "message": "ok",
            "data": {
                "content_type": "image/jpeg",
                "expires_time": 1786849851349,
                "media_asset_id": "media_39aa9699b30db86e3f4d518c",
                "size_bytes": 338532,
                "status": "uploaded",
                "upload_expires_time": 1784344251349,
                "uploaded_time": 1784258042647
            }
        }
    ]
}

#7、CreateIntentTask创建并启动 3.0 线索搜索任务请求与响应

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

#8、GetTask轮询任务状态请求与响应

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

#9、ListTaskCandidates查询候选集列表请求与响应
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

#10、GetTaskCandidateDetail单个候选详情请求与响应

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