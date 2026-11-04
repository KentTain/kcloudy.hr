"""HR 招聘渠道适配层。

结构对齐 iam 统一集成层（errors/http/credentials/providers），只管「怎么调
渠道 API」，「拿什么、怎么入库」归招聘业务服务（requisition/candidate service）。

渠道清单（一期）：智联 zhilian / 前程无忧 job51 / 猎聘 liepin；内推 internal
为内置免凭证渠道（站内职位页投递直达，不走适配层）。
"""
