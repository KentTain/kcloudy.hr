"""合同与材料附件域 DTO"""

from datetime import date

from framework.schemas import BaseModel


class ContractCreate(BaseModel):
    """新签合同"""

    employee_id: str
    contract_no: str
    contract_type: str
    start_date: date
    end_date: date | None = None
    company: str | None = None
    signed_date: date | None = None
    expiry_remind: bool = False
    attachment: str | None = None
    remark: str | None = None


class ContractRenew(BaseModel):
    """续签（旧合同区间闭合 + 新合同生效）"""

    contract_no: str
    contract_type: str
    start_date: date
    end_date: date | None = None
    company: str | None = None
    signed_date: date | None = None
    expiry_remind: bool = False
    attachment: str | None = None
    remark: str | None = None


class ContractUpdate(BaseModel):
    """合同编辑（备注/提醒开关/附件）"""

    expiry_remind: bool | None = None
    attachment: str | None = None
    remark: str | None = None


class ContractResponse(BaseModel):
    """合同记录卡"""

    id: str
    employee_id: str
    contract_no: str
    contract_type: str
    start_date: date
    end_date: date | None = None
    company: str | None = None
    signed_date: date | None = None
    status: str
    expiry_remind: bool
    attachment: str | None = None
    remark: str | None = None


class AttachmentResponse(BaseModel):
    """材料附件"""

    id: str
    employee_id: str
    doc_type: str
    file_id: str
    file_name: str
    file_url: str | None = None


class AttachmentUploadResponse(BaseModel):
    """材料附件上传结果"""

    id: str
    employee_id: str
    doc_type: str
    file_name: str
