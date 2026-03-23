"""initial schema

Revision ID: 20260323_01
Revises:
Create Date: 2026-03-23 15:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "20260323_01"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


JSONB = postgresql.JSONB(astext_type=sa.Text())
UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", UUID, nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("hashed_password", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "cases",
        sa.Column("case_id", sa.String(), nullable=False),
        sa.Column("user_id", UUID, nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("address", sa.String(), nullable=True),
        sa.Column("external_ref", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("primary_parcel_number", sa.String(), nullable=True),
        sa.Column("last_extracted_primary_parcel_number", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("parcels", JSONB, nullable=True),
        sa.Column("canonical_list", JSONB, nullable=True),
        sa.Column("scoring_results", JSONB, nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("case_id"),
    )
    op.create_index("ix_cases_user_id", "cases", ["user_id"], unique=False)

    op.create_table(
        "documents",
        sa.Column("document_id", sa.String(), nullable=False),
        sa.Column("case_id", sa.String(), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("file_path", sa.String(), nullable=False),
        sa.Column("document_type", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("ocr_blank_pages", sa.Integer(), nullable=False),
        sa.Column("ocr_low_conf_pages", sa.Integer(), nullable=False),
        sa.Column("parse_status", sa.String(), nullable=False),
        sa.Column("pages", JSONB, nullable=True),
        sa.ForeignKeyConstraint(["case_id"], ["cases.case_id"]),
        sa.PrimaryKeyConstraint("document_id"),
    )
    op.create_index("ix_documents_case_id", "documents", ["case_id"], unique=False)

    op.create_table(
        "jobs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("case_id", sa.String(), nullable=False),
        sa.Column("task_type", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("result_data", JSONB, nullable=True),
        sa.ForeignKeyConstraint(["case_id"], ["cases.case_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_jobs_case_id", "jobs", ["case_id"], unique=False)
    op.create_index("ix_jobs_status", "jobs", ["status"], unique=False)
    op.create_index("ix_jobs_task_type", "jobs", ["task_type"], unique=False)

    op.create_table(
        "reports",
        sa.Column("report_id", sa.String(), nullable=False),
        sa.Column("case_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("edited_at", sa.DateTime(), nullable=True),
        sa.Column("manually_edited", sa.Boolean(), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=True),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column("markdown_content", sa.Text(), nullable=True),
        sa.Column("target_parcel_numbers", JSONB, nullable=True),
        sa.Column("available_parcel_numbers", JSONB, nullable=True),
        sa.Column("entries", JSONB, nullable=True),
        sa.ForeignKeyConstraint(["case_id"], ["cases.case_id"]),
        sa.PrimaryKeyConstraint("report_id"),
    )
    op.create_index("ix_reports_case_id", "reports", ["case_id"], unique=False)

    op.create_table(
        "servitutter",
        sa.Column("easement_id", sa.String(), nullable=False),
        sa.Column("case_id", sa.String(), nullable=False),
        sa.Column("source_document", sa.String(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("date_reference", sa.String(), nullable=True),
        sa.Column("registered_at", sa.Date(), nullable=True),
        sa.Column("archive_number", sa.String(), nullable=True),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("summary", sa.String(), nullable=True),
        sa.Column("beneficiary", sa.String(), nullable=True),
        sa.Column("disposition_type", sa.String(), nullable=True),
        sa.Column("legal_type", sa.String(), nullable=True),
        sa.Column("relevance_for_property", sa.String(), nullable=True),
        sa.Column("construction_relevance", sa.Boolean(), nullable=False),
        sa.Column("construction_impact", sa.String(), nullable=True),
        sa.Column("action_note", sa.String(), nullable=True),
        sa.Column("applies_to_primary_parcel", sa.Boolean(), nullable=True),
        sa.Column("raw_scope_text", sa.String(), nullable=True),
        sa.Column("scope_source", sa.String(), nullable=True),
        sa.Column("scope_basis", sa.String(), nullable=True),
        sa.Column("scope_confidence", sa.Float(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("confirmed_by_attest", sa.Boolean(), nullable=False),
        sa.Column("applies_to_parcel_numbers", JSONB, nullable=True),
        sa.Column("raw_parcel_references", JSONB, nullable=True),
        sa.Column("evidence", JSONB, nullable=True),
        sa.Column("flags", JSONB, nullable=True),
        sa.ForeignKeyConstraint(["case_id"], ["cases.case_id"]),
        sa.PrimaryKeyConstraint("easement_id"),
    )
    op.create_index("ix_servitutter_case_id", "servitutter", ["case_id"], unique=False)

    op.create_table(
        "tmv_jobs",
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("case_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("last_heartbeat_at", sa.DateTime(), nullable=True),
        sa.Column("address", sa.String(), nullable=True),
        sa.Column("download_dir", sa.String(), nullable=False),
        sa.Column("imported_count", sa.Integer(), nullable=False),
        sa.Column("skipped_count", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.Column("import_result_summary", sa.String(), nullable=True),
        sa.Column("user_ready", sa.Boolean(), nullable=False),
        sa.Column("status_detail", sa.String(), nullable=True),
        sa.Column("downloaded_files", JSONB, nullable=True),
        sa.ForeignKeyConstraint(["case_id"], ["cases.case_id"]),
        sa.PrimaryKeyConstraint("job_id"),
    )
    op.create_index("ix_tmv_jobs_case_id", "tmv_jobs", ["case_id"], unique=False)

    op.create_table(
        "chunks",
        sa.Column("chunk_id", sa.String(), nullable=False),
        sa.Column("document_id", sa.String(), nullable=False),
        sa.Column("case_id", sa.String(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("char_start", sa.Integer(), nullable=False),
        sa.Column("char_end", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["cases.case_id"]),
        sa.ForeignKeyConstraint(["document_id"], ["documents.document_id"]),
        sa.PrimaryKeyConstraint("chunk_id"),
    )
    op.create_index("ix_chunks_case_id", "chunks", ["case_id"], unique=False)
    op.create_index("ix_chunks_document_id", "chunks", ["document_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_chunks_document_id", table_name="chunks")
    op.drop_index("ix_chunks_case_id", table_name="chunks")
    op.drop_table("chunks")

    op.drop_index("ix_tmv_jobs_case_id", table_name="tmv_jobs")
    op.drop_table("tmv_jobs")

    op.drop_index("ix_servitutter_case_id", table_name="servitutter")
    op.drop_table("servitutter")

    op.drop_index("ix_reports_case_id", table_name="reports")
    op.drop_table("reports")

    op.drop_index("ix_jobs_task_type", table_name="jobs")
    op.drop_index("ix_jobs_status", table_name="jobs")
    op.drop_index("ix_jobs_case_id", table_name="jobs")
    op.drop_table("jobs")

    op.drop_index("ix_documents_case_id", table_name="documents")
    op.drop_table("documents")

    op.drop_index("ix_cases_user_id", table_name="cases")
    op.drop_table("cases")

    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
