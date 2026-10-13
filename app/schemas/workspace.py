from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field


class WorkspaceItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    slug: str
    workspace_type: str
    plan: str
    role: str
    status: str
    is_active: bool = True
    is_current: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class WorkspaceRead(WorkspaceItem):
    pass


class AcceptInviteRequest(BaseModel):
    token: str
    password: Optional[str] = None


class WorkspaceListResponse(BaseModel):
    workspaces: list[WorkspaceItem]


class WorkspaceSwitchRequest(BaseModel):
    organization_id: str


class WorkspaceSwitchResponse(BaseModel):
    message: str
    active_organization: Any
    role: str
    access_token: Optional[str] = None


class WorkspaceInviteRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    role: str = Field(default="member", pattern="^(owner|admin|member)$")


class WorkspaceInviteResponse(BaseModel):
    message: str = "Invitation sent successfully."
    invite_id: str
    email: str
    role: str
    expires_at: datetime


class WorkspaceInviteAcceptResponse(BaseModel):
    message: str = "Invitation accepted successfully."
    organization_id: str
    role: str


class WorkspaceMemberRoleUpdateRequest(BaseModel):
    role: str = Field(..., min_length=1)


class UpdateMemberRoleRequest(WorkspaceMemberRoleUpdateRequest):
    pass


class WorkspaceMemberRoleUpdateResponse(BaseModel):
    message: str = "Member role updated successfully."
    user_id: str
    role: str


class WorkspaceMemberDeleteResponse(BaseModel):
    message: str = "Member removed successfully."
    user_id: str


class MemberRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: str
    email: str
    role: str
    status: str
    joined_at: Optional[datetime] = None
