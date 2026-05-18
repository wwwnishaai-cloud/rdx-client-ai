from sqlalchemy import Column, Integer, BigInteger, String, Text, ForeignKey, DateTime, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

Base = declarative_base()


class AIUser(Base):
    __tablename__ = 'ai_users'

    id = Column(Integer, primary_key=True, autoincrement=True)
    rdx_user_id = Column(String(64), unique=True, nullable=False, index=True)
    username = Column(String(64), nullable=True)
    api_key_encrypted = Column(Text, nullable=True)
    preferred_model = Column(String(64), default='llama-3.3-70b-versatile')
    is_premium = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class AISetting(Base):
    __tablename__ = 'ai_settings'

    id = Column(Integer, primary_key=True, autoincrement=True)
    setting_key = Column(String(64), unique=True, nullable=False, index=True)
    setting_value = Column(Text, nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class AISession(Base):
    __tablename__ = 'ai_sessions'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('ai_users.id'), nullable=False)
    session_token = Column(String(128), unique=True, nullable=False, index=True)
    platform = Column(String(20), nullable=False)
    platform_user_id = Column(String(128), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
    last_active = Column(DateTime, server_default=func.now(), onupdate=func.now())

    user = relationship('AIUser', backref='sessions')
    messages = relationship('AIMessage', backref='session', order_by='AIMessage.created_at')


class AIMessage(Base):
    __tablename__ = 'ai_messages'

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    session_id = Column(Integer, ForeignKey('ai_sessions.id'), nullable=False, index=True)
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    platform = Column(String(20), nullable=False)
    model_used = Column(String(64), nullable=True)
    tokens_used = Column(Integer, nullable=True, default=0)
    created_at = Column(DateTime, server_default=func.now())


class AIMemory(Base):
    __tablename__ = 'ai_memory'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('ai_users.id'), nullable=False)
    summary = Column(Text, nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    user = relationship('AIUser', backref='memories')


class AIDashboardAccess(Base):
    __tablename__ = 'ai_dashboard_access'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('ai_users.id'), nullable=False, unique=True)
    can_manage_licenses = Column(Boolean, default=False)
    can_view_analytics = Column(Boolean, default=False)
    can_manage_billing = Column(Boolean, default=False)
    can_manage_hwid = Column(Boolean, default=False)
    can_manage_security = Column(Boolean, default=False)
    granted_by = Column(String(64), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    user = relationship('AIUser', backref='dashboard_access')
