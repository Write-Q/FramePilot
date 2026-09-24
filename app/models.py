"""业务表结构；LangGraph 自己管理检查点表，不与正文历史混用。"""
from datetime import datetime
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = 'fp_projects'
    __table_args__ = (CheckConstraint('max_calls > 0', name='ck_fp_projects_budget'),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # 可变的状态和暂停信息保留为 JSONB 快照；额度和创建时间独立建列。
    snapshot: Mapped[dict] = mapped_column(JSONB)
    max_calls: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class StoryVersion(Base):
    __tablename__ = 'fp_versions'
    __table_args__ = (CheckConstraint('version >= 1', name='ck_fp_versions_positive'),)
    project_id: Mapped[str] = mapped_column(ForeignKey('fp_projects.id'), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    draft: Mapped[str] = mapped_column(Text)
    card: Mapped[dict] = mapped_column(JSONB)


class ModelCall(Base):
    __tablename__ = 'fp_calls'
    __table_args__ = (Index('ix_fp_calls_project_id_id', 'project_id', 'id'),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(ForeignKey('fp_projects.id'))
    task: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32))
    usage: Mapped[dict] = mapped_column(JSONB, default=dict)
