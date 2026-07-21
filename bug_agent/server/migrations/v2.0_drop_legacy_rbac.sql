-- v2.0 去兼容化：清理 legacy RBAC 角色与绑定
-- 目标：
-- 1) user          -> member
-- 2) project_owner -> project_admin
-- 3) guest         -> viewer
-- 4) org_admin     -> super_admin

BEGIN;

DO $$
DECLARE
    legacy_name TEXT;
    target_name TEXT;
    legacy_role_id BIGINT;
    target_role_id BIGINT;
BEGIN
    FOR legacy_name, target_name IN
        SELECT * FROM (
            VALUES
                ('user', 'member'),
                ('project_owner', 'project_admin'),
                ('guest', 'viewer'),
                ('org_admin', 'super_admin')
        ) AS m(legacy_name, target_name)
    LOOP
        SELECT id INTO legacy_role_id FROM roles WHERE name = legacy_name LIMIT 1;
        IF legacy_role_id IS NULL THEN
            CONTINUE;
        END IF;

        SELECT id INTO target_role_id FROM roles WHERE name = target_name LIMIT 1;

        IF target_role_id IS NOT NULL THEN
            -- 删除会和目标角色冲突的 user_roles 记录
            DELETE FROM user_roles ur
            USING user_roles ur2
            WHERE ur.role_id = legacy_role_id
              AND ur2.role_id = target_role_id
              AND ur.user_id = ur2.user_id
              AND COALESCE(ur.scope_type, '') = COALESCE(ur2.scope_type, '')
              AND COALESCE(ur.scope_id, 0) = COALESCE(ur2.scope_id, 0);

            -- 将剩余 legacy 绑定迁移到目标角色
            UPDATE user_roles
            SET role_id = target_role_id
            WHERE role_id = legacy_role_id;
        ELSE
            -- 无目标角色时直接删除 legacy 绑定
            DELETE FROM user_roles WHERE role_id = legacy_role_id;
        END IF;

        DELETE FROM role_permissions WHERE role_id = legacy_role_id;
        DELETE FROM roles WHERE id = legacy_role_id;
    END LOOP;
END $$;

COMMIT;

