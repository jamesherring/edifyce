-- Modify "users" table
ALTER TABLE "public"."users" ALTER COLUMN "hashed_password" TYPE character varying(1024), ALTER COLUMN "hashed_password" SET NOT NULL, ALTER COLUMN "is_active" DROP DEFAULT, ADD COLUMN "is_superuser" boolean NOT NULL, ADD COLUMN "is_verified" boolean NOT NULL;
-- Create "oauth_accounts" table
CREATE TABLE "public"."oauth_accounts" ("id" uuid NOT NULL DEFAULT gen_random_uuid(), "user_id" uuid NOT NULL, "oauth_name" character varying(100) NOT NULL, "access_token" character varying(1024) NOT NULL, "expires_at" integer NULL, "refresh_token" character varying(1024) NULL, "account_id" character varying(320) NOT NULL, "account_email" character varying(320) NOT NULL, "created_at" timestamptz NOT NULL DEFAULT now(), "updated_at" timestamptz NOT NULL DEFAULT now(), PRIMARY KEY ("id"), CONSTRAINT "fk_oauth_accounts_user_id_users" FOREIGN KEY ("user_id") REFERENCES "public"."users" ("id") ON UPDATE NO ACTION ON DELETE CASCADE);
-- Create index "ix_oauth_accounts_account_id" to table: "oauth_accounts"
CREATE INDEX "ix_oauth_accounts_account_id" ON "public"."oauth_accounts" ("account_id");
-- Create index "ix_oauth_accounts_oauth_name" to table: "oauth_accounts"
CREATE INDEX "ix_oauth_accounts_oauth_name" ON "public"."oauth_accounts" ("oauth_name");
-- Create index "ix_oauth_accounts_user_id" to table: "oauth_accounts"
CREATE INDEX "ix_oauth_accounts_user_id" ON "public"."oauth_accounts" ("user_id");
