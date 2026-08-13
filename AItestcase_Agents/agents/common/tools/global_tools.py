import base64
import random
import string
import time

try:
    import rsa
except ImportError:
    rsa = None

try:
    from faker import Faker
except ImportError:
    Faker = None

fk = Faker(locale="zh_CN") if Faker else None


def random_mobile():
    """随机生成手机号"""
    if fk is None:
        return "1" + "".join(random.choices(string.digits, k=10))
    return fk.phone_number()


def random_account():
    """6到18位的账号"""
    str_list = [
        "a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l", "m",
        "n", "o", "p", "q", "r", "s", "t", "u", "v", "w", "x", "y", "z",
        "A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M",
        "N", "O", "P", "Q", "R", "S", "T", "U", "V", "W", "X", "Y", "Z",
        "0", "1", "2", "3", "4", "5", "6", "7",
    ]
    result = ""
    for _ in range(6, 18):
        result += random.choice(str_list)
    return result


def random_name():
    """随机生成中文名字"""
    if fk is None:
        return "test_user_" + "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return fk.name()


def random_ssn():
    """随机生成一个身份证号"""
    if fk is None:
        return "".join(random.choices(string.digits, k=18))
    return fk.ssn()


def random_addr():
    """随机生成一个地址"""
    if fk is None:
        return "test_address_" + "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    return fk.address()


def random_city():
    """随机生成一个城市名"""
    if fk is None:
        return "test_city"
    return fk.city()


def random_company():
    """随机生成一个公司名"""
    if fk is None:
        return "test_company"
    return fk.company()


def random_postcode():
    """随机生成一个邮编"""
    if fk is None:
        return "".join(random.choices(string.digits, k=6))
    return fk.postcode()


def random_email():
    """随机生成一个邮箱号"""
    if fk is None:
        return "test_" + "".join(random.choices(string.ascii_lowercase + string.digits, k=8)) + "@example.com"
    return fk.email()


def random_date():
    """随机生成一个日期"""
    if fk is None:
        return time.strftime("%Y-%m-%d")
    return fk.date()


def radom_date_time():
    """随机生成一个时间"""
    if fk is None:
        return time.strftime("%Y-%m-%d %H:%M:%S")
    return fk.date_time()


def random_ipv4():
    """随机生成一个ipv4的地址"""
    if fk is None:
        return ".".join(str(random.randint(1, 254)) for _ in range(4))
    return fk.ipv4()


def random_password():
    """随机生成密码（8-16位，包含大小写字母和数字）"""
    chars = string.ascii_letters + string.digits
    length = random.randint(8, 16)
    return "".join(random.choices(chars, k=length))


def get_timestamp():
    """生成当前时间戳"""
    return time.time()


def base64_encode(data: str):
    """base64编码"""
    return base64.b64encode(data.encode("utf-8")).decode("utf-8")


def md5_encrypt(data: str):
    """md5加密"""
    from hashlib import md5

    new_md5 = md5()
    new_md5.update(data.encode("utf-8"))
    return new_md5.hexdigest()


def rsa_encrypt(msg, server_pub):
    """
    rsa加密
    :param msg: 待加密文本
    :param server_pub: 密钥
    :return:
    """
    if rsa is None:
        raise ImportError("rsa package is required for rsa_encrypt")
    msg = msg.encode("utf-8")
    pub_key = server_pub.encode("utf-8")
    public_key_obj = rsa.PublicKey.load_pkcs1_openssl_pem(pub_key)
    cryto_msg = rsa.encrypt(msg, public_key_obj)
    cipher_base64 = base64.b64encode(cryto_msg)
    return cipher_base64.decode()


if __name__ == "__main__":
    print(random_mobile())
