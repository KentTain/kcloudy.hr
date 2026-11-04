"""
HR 模块枚举定义
"""

from enum import Enum

from framework.common.enums import EnumBase


class EmployeeStatus(str, EnumBase):
    """员工状态"""

    PENDING = "pending"
    PROBATION = "probation"
    REGULAR = "regular"
    INTERN = "intern"
    OFFBOARDED = "offboarded"

    @property
    def label(self) -> str:
        labels = {
            EmployeeStatus.PENDING: "待入职",
            EmployeeStatus.PROBATION: "试用期",
            EmployeeStatus.REGULAR: "正式",
            EmployeeStatus.INTERN: "实习",
            EmployeeStatus.OFFBOARDED: "已离职",
        }
        return labels.get(self, self.name)


class PositionStatus(str, EnumBase):
    """岗位状态"""

    DRAFT = "draft"
    ACTIVE = "active"
    DISABLED = "disabled"

    @property
    def label(self) -> str:
        labels = {
            PositionStatus.DRAFT: "草稿",
            PositionStatus.ACTIVE: "生效",
            PositionStatus.DISABLED: "停用",
        }
        return labels.get(self, self.name)


class ChangeType(str, EnumBase):
    """异动类型"""

    HIRE = "hire"
    PROBATE = "probate"
    TRANSFER = "transfer"
    LEVEL_CHANGE = "level_change"
    SALARY_CHANGE = "salary_change"
    OFFBOARD = "offboard"

    @property
    def label(self) -> str:
        labels = {
            ChangeType.HIRE: "入职",
            ChangeType.PROBATE: "转正",
            ChangeType.TRANSFER: "调岗",
            ChangeType.LEVEL_CHANGE: "职级变更",
            ChangeType.SALARY_CHANGE: "调薪",
            ChangeType.OFFBOARD: "离职",
        }
        return labels.get(self, self.name)


class ContractStatus(str, EnumBase):
    """合同状态"""

    ACTIVE = "active"
    EXPIRED = "expired"
    TERMINATED = "terminated"

    @property
    def label(self) -> str:
        labels = {
            ContractStatus.ACTIVE: "生效中",
            ContractStatus.EXPIRED: "已到期",
            ContractStatus.TERMINATED: "已终止",
        }
        return labels.get(self, self.name)


class AttachmentDocType(str, EnumBase):
    """员工材料附件类型"""

    ID_CARD = "id_card"
    EDUCATION = "education"
    LABOR_CONTRACT = "labor_contract"
    ONBOARD = "onboard"
    OTHER = "other"

    @property
    def label(self) -> str:
        labels = {
            AttachmentDocType.ID_CARD: "身份证件",
            AttachmentDocType.EDUCATION: "学历证明",
            AttachmentDocType.LABOR_CONTRACT: "劳动合同",
            AttachmentDocType.ONBOARD: "入职材料",
            AttachmentDocType.OTHER: "其他",
        }
        return labels.get(self, self.name)


class AttributeDataType(str, EnumBase):
    """员工自定义属性数据类型"""

    STRING = "string"
    INTEGER = "integer"
    DECIMAL = "decimal"
    DATE_TIME = "date_time"
    BOOLEAN = "boolean"
    JSON = "json"

    @property
    def label(self) -> str:
        labels = {
            AttributeDataType.STRING: "文本",
            AttributeDataType.INTEGER: "整数",
            AttributeDataType.DECIMAL: "小数",
            AttributeDataType.DATE_TIME: "日期",
            AttributeDataType.BOOLEAN: "布尔",
            AttributeDataType.JSON: "JSON",
        }
        return labels.get(self, self.name)


class RequisitionPriority(str, EnumBase):
    """招聘需求优先级"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"

    @property
    def label(self) -> str:
        labels = {
            RequisitionPriority.LOW: "低",
            RequisitionPriority.MEDIUM: "中",
            RequisitionPriority.HIGH: "高",
            RequisitionPriority.URGENT: "紧急",
        }
        return labels.get(self, self.name)


class RequisitionStatus(str, EnumBase):
    """招聘需求状态"""

    DRAFT = "draft"
    RECRUITING = "recruiting"
    PARTIAL = "partial"
    FILLED = "filled"
    CLOSED = "closed"

    @property
    def label(self) -> str:
        labels = {
            RequisitionStatus.DRAFT: "草稿",
            RequisitionStatus.RECRUITING: "招聘中",
            RequisitionStatus.PARTIAL: "部分到岗",
            RequisitionStatus.FILLED: "已满编",
            RequisitionStatus.CLOSED: "已关闭",
        }
        return labels.get(self, self.name)


class PostingStatus(str, EnumBase):
    """职位发布状态"""

    PUBLISHING = "publishing"
    PUBLISHED = "published"
    OFFLINE = "offline"

    @property
    def label(self) -> str:
        labels = {
            PostingStatus.PUBLISHING: "发布中",
            PostingStatus.PUBLISHED: "已发布",
            PostingStatus.OFFLINE: "已下线",
        }
        return labels.get(self, self.name)


class RecruitingChannel(str, EnumBase):
    """招聘渠道"""

    INTERNAL = "internal"
    ZHILIAN = "zhilian"
    JOB51 = "job51"
    LIEPIN = "liepin"

    @property
    def label(self) -> str:
        labels = {
            RecruitingChannel.INTERNAL: "内部推荐",
            RecruitingChannel.ZHILIAN: "智联招聘",
            RecruitingChannel.JOB51: "前程无忧",
            RecruitingChannel.LIEPIN: "猎聘",
        }
        return labels.get(self, self.name)


class ApplicationStage(str, EnumBase):
    """候选人投递阶段（三段漏斗：初筛→面试→录用）"""

    PENDING_SCREENING = "pending_screening"
    SCREENING_PASSED = "screening_passed"
    INTERVIEWING = "interviewing"
    PRE_HIRE = "pre_hire"
    OFFERED = "offered"
    PRE_ONBOARD = "pre_onboard"
    ONBOARDED = "onboarded"
    ONBOARD_ABANDONED = "onboard_abandoned"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"

    @property
    def label(self) -> str:
        labels = {
            ApplicationStage.PENDING_SCREENING: "待初筛",
            ApplicationStage.SCREENING_PASSED: "初筛通过",
            ApplicationStage.INTERVIEWING: "面试中",
            ApplicationStage.PRE_HIRE: "待发Offer",
            ApplicationStage.OFFERED: "已发Offer",
            ApplicationStage.PRE_ONBOARD: "待入职",
            ApplicationStage.ONBOARDED: "已入职",
            ApplicationStage.ONBOARD_ABANDONED: "放弃入职",
            ApplicationStage.REJECTED: "已淘汰",
            ApplicationStage.WITHDRAWN: "已放弃",
        }
        return labels.get(self, self.name)


class OfferStatus(str, EnumBase):
    """Offer 状态"""

    PENDING = "pending"
    SENT = "sent"
    ACCEPTED = "accepted"
    REJECTED = "rejected"

    @property
    def label(self) -> str:
        labels = {
            OfferStatus.PENDING: "待发送",
            OfferStatus.SENT: "已发送",
            OfferStatus.ACCEPTED: "已接受",
            OfferStatus.REJECTED: "已拒绝",
        }
        return labels.get(self, self.name)


class InterviewForm(str, EnumBase):
    """面试形式"""

    ONSITE = "onsite"
    VIDEO = "video"
    PHONE = "phone"

    @property
    def label(self) -> str:
        labels = {
            InterviewForm.ONSITE: "现场",
            InterviewForm.VIDEO: "视频",
            InterviewForm.PHONE: "电话",
        }
        return labels.get(self, self.name)


class InterviewResult(str, EnumBase):
    """面试结果"""

    PENDING = "pending"
    PASS = "pass"
    FAIL = "fail"

    @property
    def label(self) -> str:
        labels = {
            InterviewResult.PENDING: "待面试",
            InterviewResult.PASS: "通过",
            InterviewResult.FAIL: "未通过",
        }
        return labels.get(self, self.name)


class SalaryChangeReason(str, EnumBase):
    """定薪/调薪原因"""

    HIRE = "hire"
    ADJUST = "adjust"
    PROMOTION = "promotion"
    PERF = "perf"

    @property
    def label(self) -> str:
        labels = {
            SalaryChangeReason.HIRE: "入职定薪",
            SalaryChangeReason.ADJUST: "调薪",
            SalaryChangeReason.PROMOTION: "晋升调薪",
            SalaryChangeReason.PERF: "绩效联动",
        }
        return labels.get(self, self.name)


class PayrollStatus(str, EnumBase):
    """发薪批次状态"""

    DRAFT = "draft"
    CONFIRMED = "confirmed"
    PAID = "paid"
    CANCELLED = "cancelled"

    @property
    def label(self) -> str:
        labels = {
            PayrollStatus.DRAFT: "草稿",
            PayrollStatus.CONFIRMED: "已确认",
            PayrollStatus.PAID: "已发放",
            PayrollStatus.CANCELLED: "已取消",
        }
        return labels.get(self, self.name)


class AttendanceStatus(str, EnumBase):
    """考勤状态"""

    NORMAL = "normal"
    LATE = "late"
    EARLY_LEAVE = "early_leave"
    LATE_EARLY = "late_early"
    ABSENT = "absent"
    MISSING_CARD = "missing_card"
    LEAVE = "leave"
    TRIP = "trip"

    @property
    def label(self) -> str:
        labels = {
            AttendanceStatus.NORMAL: "正常",
            AttendanceStatus.LATE: "迟到",
            AttendanceStatus.EARLY_LEAVE: "早退",
            AttendanceStatus.LATE_EARLY: "迟到且早退",
            AttendanceStatus.ABSENT: "缺勤",
            AttendanceStatus.MISSING_CARD: "缺卡",
            AttendanceStatus.LEAVE: "请假",
            AttendanceStatus.TRIP: "出差",
        }
        return labels.get(self, self.name)


class AttendanceSource(str, EnumBase):
    """考勤记录来源"""

    EXCEL = "excel"
    AI = "ai"
    LEAVE = "leave"

    @property
    def label(self) -> str:
        labels = {
            AttendanceSource.EXCEL: "Excel导入",
            AttendanceSource.AI: "AI导入",
            AttendanceSource.LEAVE: "请假联动",
        }
        return labels.get(self, self.name)


class ImportBatchStatus(str, EnumBase):
    """考勤导入批次状态"""

    PENDING = "pending"
    PARSING = "parsing"
    PARSED = "parsed"
    COMPLETED = "completed"
    FAILED = "failed"

    @property
    def label(self) -> str:
        labels = {
            ImportBatchStatus.PENDING: "已上传",
            ImportBatchStatus.PARSING: "解析中",
            ImportBatchStatus.PARSED: "解析完成",
            ImportBatchStatus.COMPLETED: "已完成",
            ImportBatchStatus.FAILED: "失败",
        }
        return labels.get(self, self.name)


class LeaveUnit(str, EnumBase):
    """假期计量单位"""

    DAY = "day"
    HOUR = "hour"

    @property
    def label(self) -> str:
        labels = {
            LeaveUnit.DAY: "天",
            LeaveUnit.HOUR: "小时",
        }
        return labels.get(self, self.name)


class QuotaRule(str, EnumBase):
    """假期额度规则"""

    ANNUAL_FIXED = "annual_fixed"
    MANUAL = "manual"

    @property
    def label(self) -> str:
        labels = {
            QuotaRule.ANNUAL_FIXED: "按年度固定额度",
            QuotaRule.MANUAL: "仅手工调整",
        }
        return labels.get(self, self.name)


class LeaveTypeStatus(str, EnumBase):
    """假期类型状态"""

    ENABLED = "enabled"
    DISABLED = "disabled"

    @property
    def label(self) -> str:
        labels = {
            LeaveTypeStatus.ENABLED: "启用",
            LeaveTypeStatus.DISABLED: "停用",
        }
        return labels.get(self, self.name)


class LeaveRequestStatus(str, EnumBase):
    """请假单状态"""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"

    @property
    def label(self) -> str:
        labels = {
            LeaveRequestStatus.PENDING: "待审批",
            LeaveRequestStatus.APPROVED: "已通过",
            LeaveRequestStatus.REJECTED: "已驳回",
            LeaveRequestStatus.CANCELLED: "已撤销",
        }
        return labels.get(self, self.name)


class ApprovalBizType(str, EnumBase):
    """审批业务类型"""

    PROFILE_CHANGE = "profile_change"

    @property
    def label(self) -> str:
        labels = {
            ApprovalBizType.PROFILE_CHANGE: "档案变更申请",
        }
        return labels.get(self, self.name)


class ApprovalStatus(str, EnumBase):
    """审批请求状态"""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"

    @property
    def label(self) -> str:
        labels = {
            ApprovalStatus.PENDING: "待审批",
            ApprovalStatus.APPROVED: "已通过",
            ApprovalStatus.REJECTED: "已驳回",
            ApprovalStatus.CANCELLED: "已撤销",
        }
        return labels.get(self, self.name)


class PerfCycleStatus(str, EnumBase):
    """考核周期状态（单向推进）"""

    DRAFT = "draft"
    ACTIVE = "active"
    SCORING = "scoring"
    CALIBRATING = "calibrating"
    CLOSED = "closed"

    @property
    def label(self) -> str:
        labels = {
            PerfCycleStatus.DRAFT: "草稿",
            PerfCycleStatus.ACTIVE: "进行中",
            PerfCycleStatus.SCORING: "评分中",
            PerfCycleStatus.CALIBRATING: "校准中",
            PerfCycleStatus.CLOSED: "已收口",
        }
        return labels.get(self, self.name)


class PerfGoalStatus(str, EnumBase):
    """绩效目标状态"""

    OPEN = "open"
    COMPLETED = "completed"

    @property
    def label(self) -> str:
        labels = {
            PerfGoalStatus.OPEN: "进行中",
            PerfGoalStatus.COMPLETED: "已完成",
        }
        return labels.get(self, self.name)


class PerfReviewStatus(str, EnumBase):
    """绩效评估状态"""

    PENDING = "pending"
    SUBMITTED = "submitted"
    CALIBRATED = "calibrated"

    @property
    def label(self) -> str:
        labels = {
            PerfReviewStatus.PENDING: "待评分",
            PerfReviewStatus.SUBMITTED: "已评分",
            PerfReviewStatus.CALIBRATED: "已校准",
        }
        return labels.get(self, self.name)


class PerfRating(str, EnumBase):
    """绩效评级"""

    S = "S"
    A = "A"
    B = "B"
    C = "C"
    D = "D"

    @property
    def label(self) -> str:
        return self.value


class ApprovalActionType(str, EnumBase):
    """审批流水动作"""

    SUBMIT = "submit"
    APPROVE = "approve"
    REJECT = "reject"
    CANCEL = "cancel"

    @property
    def label(self) -> str:
        labels = {
            ApprovalActionType.SUBMIT: "提交",
            ApprovalActionType.APPROVE: "通过",
            ApprovalActionType.REJECT: "驳回",
            ApprovalActionType.CANCEL: "撤销",
        }
        return labels.get(self, self.name)
