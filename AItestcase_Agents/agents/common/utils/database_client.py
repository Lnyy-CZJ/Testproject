# @Author  : 木森
# @weixin: python771
"""
一个项目设计到多个数据
    每个数据库有不同的配置

"""
import pymysql


class MySQLClient:
    """mysql数据库连接的类"""

    def __init__(self, config):
        try:
            # 连接数据库
            self.db_connect = pymysql.connect(**config)
            # 初始化一个游标对象（查询到的每条数据作为一个字典进行返回）
            self.db_cursor = self.db_connect.cursor(pymysql.cursors.DictCursor)
        except Exception as e:
            pass

    def execute(self, query):
        """
        :param query: sql语句
        :return:
        """
        self.db_cursor.execute(query)
        return self.db_cursor.fetchall()

    def close(self):
        """关闭数据库连接"""
        self.db_cursor.close()
        self.db_connect.close()


class DBClient:
    """数据库连接的客户端"""

    def __init__(self, db_config):
        """初始化数据库连接"""
        # 初始化一个连接池，保存数据连接的连接池
        self.db_pool = {}
        for db_item in db_config:
            # 判断数据库的类型
            if db_item["type"] == "mysql":
                # 调用mysql数据库连接方法进行初始化连接
                self.mysql_database_connection(db_item)
            elif db_item["type"] == "mongodb":
                # 调用mongodb数据库连接方法进行初始化连接
                self.mongodb_database_connection(db_item)
            elif db_item["type"] == "redis":
                # 调用redis数据库连接方法进行初始化连接
                self.redis_database_connection(db_item)
            elif db_item["type"] == "sqlite":
                # 调用sqlite数据库连接方法进行初始化连接
                self.sqlite_database_connection(db_item)
            elif db_item["type"] == "oracle":
                # 调用oracle数据库连接方法进行初始化连接
                self.oracle_database_connection(db_item)
            elif db_item["type"] == "postgresql":
                # 调用postgresql数据库连接方法进行初始化连接
                self.postgresql_database_connection(db_item)
            else:
                raise Exception("数据库类型错误")

    def close(self):
        """关闭数据库连接"""
        for db_name, db_connect in self.db_pool.items():
            db_connect.close()

    def mysql_database_connection(self, db_config: dict):
        """创建mysql数据库的连接"""
        # 连接名称
        db_name = db_config["name"]
        # 获取数据库连接的配置信息
        db_config = db_config["config"]
        # 创建数据库连接
        db_connect = MySQLClient(db_config)
        # 将连接对象设置为属性
        setattr(self, db_name, db_connect)
        # 将该数据库的连接保存到连接池
        self.db_pool[db_name] = db_connect

    def mongodb_database_connection(self, db_config: dict):
        """创建mongodb数据库的连接"""
        # 连接名称
        db_name = db_config["name"]
        # 获取数据库连接的配置信息
        db_config = db_config["config"]
        # 使用pymysql模块进行连接

    def redis_database_connection(self, db_config: dict):
        """创建redis数据库的连接"""
        # 使用redis模型进行连接

    def sqlite_database_connection(self, db_config: dict):
        """创建sqlite数据库的连接"""
        # 使用sqlite3模块进行连接

    def oracle_database_connection(self, db_config: dict):
        """创建oracle数据库的连接"""
        # 使用cx_Oracle模块进行连接

    def postgresql_database_connection(self, db_config: dict):
        """创建postgresql数据库的连接"""
        # 使用psycopg2模块进行连接
