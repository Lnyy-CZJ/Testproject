case_common:
  baseURL: "http://shop-xo.hctestedu.com/index.php?s="
  headers:
    application:
      value: "web"
      param_role: fixed
      fixed_value: "web"
      baseline_value: "web"
    application_client_type:
      value: "PC"
      param_role: fixed
      fixed_value: "PC"
      baseline_value: "PC"
    Content-Type:
      value: "application/json"
      param_role: fixed
      fixed_value: "application/json"
      baseline_value: "application/json"

login:
  description: 登录接口
  method: POST
  login_URL: "/api/user/login"

  body:
    type:
      value: "username"
      param_role: fixed
      fixed_value: "username"
      baseline_value: "username"

    accounts:
      value: "czj11"
      param_role: required
      baseline_value: "czj11"
      data_category: baseline

    pwd:
      value: "czj111"
      param_role: required
      baseline_value: "czj111"
      data_category: baseline

    verify:
      value: "1234"
      param_role: optional
      default_value: "1234"
      baseline_value: "1234"
      data_category: baseline
