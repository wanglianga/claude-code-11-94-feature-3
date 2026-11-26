export const PACK_STATUS = {
  received: '接收',
  quarantined: '隔离',
  dismantling: '拆解',
  pending_inspection: '待检',
  pending_approval: '待审批',
  reusable: '可复用',
  pending_recycle: '待回收',
  outbound: '已出库',
}

export const APPROVAL_STATUS = { active: '有效', voided: '已失效', superseded: '已替代' }
export const DECISION = { echelon: '梯次利用', recycle: '回收', reinspect: '退回补检' }
export const PICKING_STATUS = { waiting: '待拣货', corrected: '已更正', picked: '已拣货', cancelled: '已取消' }
export const OUTBOUND_STATUS = {
  created: '已建单', notified: '已通知买家', shipped: '已装车',
  rejected: '买家拒收', recalled: '召回', returned: '退运', signed: '已签收',
}
export const MODULE_STATUS = {
  linked: '已建立父子关系', quarantine_review: '隔离待核', reusable: '可复用',
  pending_recycle: '待回收', outbound: '已出库', rejected_returned: '拒收退回待复核',
}
export const EVENT_TYPE = { collision: '碰撞', water: '浸水', thermal: '热事件' }
export const WO_STATUS = {
  created: '已创建', in_progress: '进行中', pending_verification: '待核（挂起）', completed: '已完成',
}

// ---------------- 售后客服 ----------------
export const AS_PATH = {
  advance_replace: '先寄替换件后收旧件',
  inspect_first: '先收旧件复检后换货',
}
export const AS_CASE_STATUS = { open: '办理中', closed: '已结案', withdrawn: '已撤案' }
export const LIABILITY = {
  undetermined: '责任未确定', supplier: '供应商责任', transport: '运输责任',
  customer: '客户责任', shared: '分担责任',
}
export const DEPOSIT_STATUS = {
  not_required: '无需押金', pending: '待收取', paid: '已收取/托管中',
  refund_pending: '退款处理中', refund_unknown: '退款结果未知',
  refunded: '已退款', forfeited: '已扣除',
}
export const RETURN_STATUS = { not_sent: '未寄回', in_transit: '回收在途', received: '已实收' }
export const SHIP_STATUS = { pending: '待寄出', shipped: '已寄出' }
export const SIGN_STATUS = { pending: '待签收', signed: '客户已签收' }
export const INSP_STATUS = { not_started: '未开始', in_progress: '检测中', concluded: '已结论' }
export const INSP_RESULT = {
  terminal_repairable: '可仅修端子', repairable: '可维修', no_fault: '无故障',
  fault_confirmed: '故障成立/建议换货', scrap: '报废',
}
export const DISPOSITION = {
  pending: '去向待登记', rework_stock: '返修库存', terminal_repair: '端子维修',
  repaired_returned: '修复后退回', scrapped: '报废', returned_customer: '原机退回客户',
}
export const PLAN_STATUS = { candidate: '候选（不占库存）', approved: '已批准出库', stale: '已退回（依据变化）' }
export const UNIT_STATUS = {
  available: '可用', allocated: '已批准待寄', shipped: '已寄出',
  installed: '客户已安装', consumed: '已消耗/处置',
}

export function asTagClass(status) {
  if (['refund_unknown', 'stale', 'overdue', 'withdrawn'].includes(status)) return 'red'
  if (['refunded', 'signed', 'received', 'closed', 'approved', 'concluded'].includes(status)) return 'green'
  if (['paid', 'in_transit', 'shipped', 'allocated', 'candidate', 'in_progress', 'pending'].includes(status)) return 'amber'
  if (['installed', 'consumed'].includes(status)) return 'gray'
  return ''
}

export function tagClass(status) {
  if (['quarantined', 'voided', 'corrected', 'rejected', 'fail', 'pending_verification'].includes(status)) return 'red'
  if (['reusable', 'picked', 'signed', 'pass', 'completed', 'linked'].includes(status)) return 'green'
  if (['pending_approval', 'pending_inspection', 'waiting', 'notified', 'created', 'dismantling', 'received', 'in_progress'].includes(status)) return 'amber'
  if (['outbound', 'shipped', 'recalled', 'returned', 'closed'].includes(status)) return 'gray'
  return ''
}
