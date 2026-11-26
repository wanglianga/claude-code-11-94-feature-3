<template>
  <div>
    <!-- 五个必演场景入口 -->
    <div class="panel demo-strip">
      <h2>🎬 售后五大演示场景</h2>
      <div class="demo-cards">
        <div class="demo-card" @click="selectCase('AS-O31')">
          <b>① 两条路径 · 先换后旧</b>
          <span>O-31：保修边界、押金、唯一兼容件竞争，走通寄出→签收→回收→检测→退款→结案</span>
        </div>
        <div class="demo-card" @click="selectCase('AS-O36')">
          <b>② 两条路径 · 先检后换</b>
          <span>O-36：停机 30h、旧件在途、付款暂缓；实收→复检结论→换货指派→处置→结案</span>
        </div>
        <div class="demo-card" @click="$router.push('/assignment')">
          <b>③ 竞争最后备件 / 安全资格撤回</b>
          <span>指派工作台：O-31 vs O-32 稳定决胜、R1/R2、6×8=20160 搜索统计、一键演示撤回</span>
        </div>
        <div class="demo-card" @click="selectCase('AS-O42')">
          <b>④ 押金退款未知</b>
          <span>O-42：实物已结清，唯一阻塞是退款结果未知；向通道查询确认后方可结案</span>
        </div>
        <div class="demo-card" @click="selectCase('AS-O41')">
          <b>⑤ 回收逾期</b>
          <span>O-41：旧件未寄回已逾期、计划联系时间已过，页面红色预警且不能结案</span>
        </div>
      </div>
      <div class="row" style="margin-top:10px">
        <button class="ghost danger" @click="resetDemo">重置售后演示数据</button>
        <span class="small muted">完整操作权限可用测试账号 <b>u_admin</b>（或冯售后/蒋工程/钱财务/孙仓储）</span>
      </div>
    </div>

    <div v-if="msg" class="msg ok">{{ msg }}</div>
    <div v-if="err" class="msg err">{{ err }}</div>

    <div class="as-layout">
      <!-- 案件列表 -->
      <div class="panel case-list">
        <h2>售后案件（{{ cases.length }}）</h2>
        <div v-for="c in cases" :key="c.case_no"
             class="case-item" :class="{ active: no === c.case_no }"
             @click="selectCase(c.case_no)">
          <div class="row between">
            <b>{{ c.customer_code }}</b>
            <span class="tag" :class="asTagClass(c.status)">{{ AS_CASE_STATUS[c.status] || c.status }}</span>
          </div>
          <div class="small muted">{{ c.case_no }} · {{ AS_PATH[c.path] }}</div>
          <div class="small" style="margin:4px 0">{{ c.title }}</div>
          <div class="pill-list">
            <span class="tag" :class="asTagClass(c.liability_status)">{{ LIABILITY[c.liability_status] }}</span>
            <span v-if="c.return_overdue" class="tag red">回收逾期</span>
            <span v-if="c.next_contact && c.next_contact.overdue" class="tag red">联系逾期</span>
            <span v-if="c.closure_blocker_count" class="tag amber">{{ c.closure_blocker_count }} 项待办</span>
          </div>
        </div>
      </div>

      <!-- 案件详情 -->
      <div v-if="d" class="case-detail">
        <div class="panel">
          <div class="row between wrap">
            <div>
              <h2 style="margin-bottom:4px">{{ d.customer_code }} · {{ d.title }}</h2>
              <div class="small muted">{{ d.case_no }} · 整机序列号 <span class="mono">{{ d.module_serial }}</span>
                · {{ AS_PATH[d.path] }}</div>
            </div>
            <div class="row">
              <span class="tag" :class="asTagClass(d.status)">{{ AS_CASE_STATUS[d.status] }}</span>
              <button class="ghost" @click="loadAll">刷新</button>
            </div>
          </div>

          <!-- 四个必须显示的跟踪字段 -->
          <div class="kpi4">
            <div class="kpi">
              <label>当前保管人</label>
              <div class="kpi-v">{{ d.custodian_name }}</div>
              <div class="small muted">{{ PARTY[d.custodian_party] || d.custodian_party }}</div>
            </div>
            <div class="kpi">
              <label>停机时段</label>
              <div class="kpi-v" :class="{ warn: d.downtime && d.downtime.ongoing }">
                {{ d.downtime ? d.downtime.text : '未登记停机' }}
              </div>
              <div class="small muted" v-if="d.downtime">{{ fmt(d.downtime.started_at) }} 起</div>
            </div>
            <div class="kpi">
              <label>剩余承诺</label>
              <div class="kpi-v" :class="{ danger: d.commitment && d.commitment.overdue }">
                {{ d.commitment ? d.commitment.text : '未设承诺时限' }}
              </div>
              <div class="small muted">{{ d.commitment_note }}</div>
            </div>
            <div class="kpi">
              <label>下一次联系</label>
              <div class="kpi-v" :class="{ danger: d.next_contact && d.next_contact.overdue }">
                {{ d.next_contact.at ? fmt(d.next_contact.at) : '未安排' }}
              </div>
              <div class="small muted">{{ d.next_contact.note }}
                <b v-if="d.next_contact && d.next_contact.overdue" class="danger">（已过时间）</b>
              </div>
            </div>
          </div>
        </div>

        <!-- 结案阻塞 -->
        <div class="panel" :class="d.closed ? 'closed-panel' : ''">
          <h2>✅ 结案门禁</h2>
          <div v-if="d.closed" class="msg ok">案件已于 {{ fmt(d.closed_at) }} 结案：{{ d.closure_note }}。
            原申诉与工程解释继续保留。</div>
          <template v-else>
            <div v-if="!d.closure_blockers.length" class="msg ok">实物与资金待办均已结清，可以结案。</div>
            <div v-else class="msg err">
              <div v-for="b in d.closure_blockers" :key="b.code">• {{ b.message }}</div>
            </div>
            <div class="row">
              <button :disabled="!!d.closure_blockers.length" @click="closeCase">两清结案</button>
              <button class="ghost danger" @click="withdraw">撤案（已寄备件不恢复库存）</button>
            </div>
          </template>
        </div>

        <div class="two-col">
          <!-- 左列 -->
          <div>
            <!-- 保修 -->
            <div class="panel">
              <h2>📜 保修合同解释（持续展示）</h2>
              <div class="kv">
                <span class="k">验收时间</span><span>{{ fmt(d.accepted_at) }}</span>
                <span class="k">保修起</span><span>{{ fmt(d.warranty.warranty_start) }}（验收当日 00:00）</span>
                <span class="k">保修止</span><span>{{ fmt(d.warranty.warranty_end) }}（此时点起出保，右端不含）</span>
                <span class="k">申诉时间</span>
                <span>{{ fmt(d.warranty.appealed_at) }}
                  <span class="tag green" v-if="d.warranty.appealed_in_window">申诉在保期内</span>
                  <span class="tag red" v-else>申诉已出保</span>
                </span>
              </div>
              <div class="msg info" style="margin-top:8px">{{ d.warranty.rule }}</div>
              <div class="msg warn-inline">⚖️ {{ d.warranty.liability_notice }}</div>
              <h3>原申诉（保留原文，不可覆盖）</h3>
              <div class="preserved">{{ d.original_appeal }}</div>
              <h3>工程解释（保留）</h3>
              <div class="preserved">{{ d.engineering_explanation }}</div>
              <h3>责任结论</h3>
              <div class="row">
                <span class="tag" :class="asTagClass(d.liability_status)">{{ LIABILITY[d.liability_status] }}</span>
                <span class="small">{{ d.liability_basis }}</span>
              </div>
              <div class="grid cols-2" style="margin-top:8px" v-if="!d.closed">
                <select v-model="liab.liability">
                  <option value="supplier">供应商责任</option>
                  <option value="transport">运输责任</option>
                  <option value="customer">客户责任</option>
                  <option value="shared">分担责任</option>
                </select>
                <input v-model="liab.rationale" placeholder="结论依据（须引用检测/补核结论）" />
                <button class="secondary" @click="decideLiability">出具责任结论（工程）</button>
              </div>
            </div>

            <!-- 工程补核 -->
            <div class="panel">
              <h2>🔍 工程补核（备注不能替代结论）</h2>
              <div v-for="c in d.engineering_checks" :key="c.id" class="check-row">
                <div class="row between">
                  <b>{{ c.title }}</b>
                  <span class="tag" :class="asTagClass(c.status)">
                    {{ c.status === 'concluded' ? (c.result === 'confirmed' ? '补核确认' : '排除') : '待补核' }}
                  </span>
                </div>
                <div class="small muted">{{ c.description }}</div>
                <div v-if="c.status === 'concluded'" class="small">
                  结论：{{ c.conclusion }} —— {{ c.engineer_name }} {{ fmt(c.concluded_at) }}
                </div>
                <div v-else class="row" style="margin-top:6px">
                  <select v-model="checkDraft[c.id].result" style="width:130px">
                    <option value="ruled_out">排除</option>
                    <option value="confirmed">确认</option>
                  </select>
                  <input v-model="checkDraft[c.id].conclusion" placeholder="必须填写补核结论" />
                  <button class="secondary" @click="concludeCheck(c.id)">出结论</button>
                </div>
              </div>
              <div class="row" style="margin-top:8px" v-if="!d.closed">
                <input v-model="newCheck.title" placeholder="新增补核项标题" style="flex:1" />
                <button class="ghost" @click="addCheck">新增补核项</button>
              </div>
            </div>

            <!-- 联系与承诺 -->
            <div class="panel">
              <h2>📞 联系记录与承诺管理</h2>
              <div class="grid cols-2">
                <label>新承诺时限<input type="datetime-local" v-model="sched.commitment" /></label>
                <label>承诺说明<input v-model="sched.commitment_note" /></label>
                <label>下次联系时间<input type="datetime-local" v-model="sched.next" /></label>
                <label>下次联系事项<input v-model="sched.next_note" /></label>
              </div>
              <div class="row end" style="margin-top:8px"><button class="secondary" @click="saveSchedule">保存日程/承诺</button></div>
              <hr />
              <div class="row">
                <select v-model="contact.channel" style="width:110px">
                  <option value="phone">电话</option><option value="im">即时消息</option>
                  <option value="onsite">现场</option><option value="letter">函件</option>
                </select>
                <input v-model="contact.note" placeholder="本次沟通内容（备注不会替代任何结论）" style="flex:1" />
                <label class="row" style="margin:0;gap:4px">
                  <input type="datetime-local" v-model="contact.next" style="width:190px" />
                </label>
                <button @click="addContact">记录联系</button>
              </div>
              <table style="margin-top:10px">
                <tbody>
                  <tr v-for="c in d.contacts" :key="c.id">
                    <td style="width:130px" class="small muted">{{ fmt(c.created_at) }}</td>
                    <td style="width:70px">{{ CHANNEL[c.channel] || c.channel }}</td>
                    <td class="small">{{ c.note }}</td>
                    <td style="width:90px" class="small muted">{{ c.actor_name }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <!-- 右列 -->
          <div>
            <!-- 办理要素 -->
            <div class="panel">
              <h2>🧰 办理要素</h2>
              <div class="row wrap" style="gap:14px">
                <div>
                  <label>材料</label>
                  <span class="tag" :class="d.materials_complete ? 'green' : 'red'">
                    {{ d.materials_complete ? '已收齐' : '未收齐' }}</span>
                  <button class="ghost xs" @click="act(`/cases/${no}/materials`,{complete:!d.materials_complete})">
                    {{ d.materials_complete ? '标记未齐' : '标记收齐' }}</button>
                </div>
                <div>
                  <label>停机时段</label>
                  <button class="ghost xs" @click="act(`/cases/${no}/downtime`,{action:'start'})">开始</button>
                  <button class="ghost xs" @click="act(`/cases/${no}/downtime`,{action:'end'})">结束</button>
                </div>
              </div>
              <h3>保管人转移</h3>
              <div class="row">
                <select v-model="custody.party" style="width:120px">
                  <option value="customer">客户</option><option value="logistics">物流</option>
                  <option value="warehouse">售后仓</option><option value="lab">检测/工程区</option>
                </select>
                <input v-model="custody.name" placeholder="保管人/单位名称" style="width:180px" />
                <input v-model="custody.note" placeholder="交接说明" />
                <button class="secondary" @click="transferCustody">转移</button>
              </div>
              <h3>保管台账</h3>
              <div v-for="e in d.custody_events.slice(0,6)" :key="e.id" class="small custody-line">
                <span class="muted">{{ fmt(e.created_at) }}</span>
                [{{ e.scope === 'replacement' ? '替换件' : '旧件' }}]
                {{ e.from_party || '—' }} → <b>{{ e.to_party }}</b>
                <span class="muted">{{ e.note }}</span>
              </div>
            </div>

            <!-- 资金 -->
            <div class="panel">
              <h2>💰 押金与付款</h2>
              <div class="row wrap">
                <span class="tag" :class="asTagClass(d.deposit && d.deposit.status)">
                  押金：{{ d.deposit ? (DEPOSIT_STATUS[d.deposit.status] || d.deposit.status) : '未登记' }}
                </span>
                <b v-if="d.deposit" class="mono">¥{{ d.deposit.amount }}</b>
                <span v-if="d.deposit && d.deposit.gateway_ref" class="small muted">{{ d.deposit.gateway_ref }}</span>
              </div>
              <div class="row wrap" style="margin-top:8px" v-if="!d.closed">
                <input type="number" v-model.number="depositAmount" style="width:110px" placeholder="金额" />
                <button class="ghost xs" @click="act(`/cases/${no}/deposit/require`,{amount:depositAmount})">登记金额</button>
                <button class="secondary xs" @click="act(`/cases/${no}/deposit/pay`,{amount:depositAmount||null})">确认收讫</button>
                <button class="ghost xs" @click="act(`/cases/${no}/deposit/refund-request`,{})">发起退款→通道未知</button>
                <button class="secondary xs" @click="act(`/cases/${no}/deposit/refund-query`,{})">向通道查询</button>
                <button class="ghost danger xs" @click="act(`/cases/${no}/deposit/forfeit`,{reason:'按约扣除'})">扣除押金</button>
              </div>
              <div v-if="d.deposit && d.deposit.status==='refund_unknown'" class="msg err" style="margin-top:8px">
                退款通道未返回明确结果（查询 {{ d.deposit.query_count }} 次）：未知不等于已退，结案资金门禁不放行。
              </div>
              <hr />
              <div class="row wrap">
                <span class="tag" :class="d.payment_held ? 'amber' : 'green'">
                  付款暂缓：{{ d.payment_held ? (d.payment_resolved ? '已处置' : '暂缓中') : '未暂缓' }}
                </span>
                <span class="small muted">{{ d.payment_hold_reason }}</span>
              </div>
              <div class="row wrap" style="margin-top:8px" v-if="!d.closed">
                <button class="ghost xs" @click="act(`/cases/${no}/payment-hold`,{held:true,reason:'复检结论前暂缓'})">设置暂缓</button>
                <select v-model="payResolution" style="width:150px">
                  <option value="released">放行付款</option>
                  <option value="deducted">扣减后结清</option>
                  <option value="waived">豁免</option>
                </select>
                <button class="secondary xs" @click="act(`/cases/${no}/payment-resolve`,{resolution:payResolution})">处置暂缓</button>
              </div>
            </div>

            <!-- 替换件 -->
            <div class="panel">
              <h2>📦 替换件寄递（寄出① / 签收② 独立）</h2>
              <table>
                <thead><tr><th>序列号</th><th>寄出</th><th>签收</th><th>操作</th></tr></thead>
                <tbody>
                  <tr v-for="o in d.replacement_orders" :key="o.id">
                    <td class="mono small">{{ o.spare_serial }}<div class="muted">{{ o.tracking_no }}</div></td>
                    <td><span class="tag" :class="asTagClass(o.shipment_status)">{{ SHIP_STATUS[o.shipment_status] }}</span>
                      <div class="small muted">{{ fmt(o.shipped_at) }}</div></td>
                    <td><span class="tag" :class="asTagClass(o.signoff_status)">{{ SIGN_STATUS[o.signoff_status] }}</span>
                      <div class="small muted">{{ o.signer }} {{ fmt(o.signed_at) }}</div></td>
                    <td>
                      <button v-if="o.shipment_status==='pending'" class="xs"
                              @click="act(`/replacement-orders/${o.id}/ship`,{tracking_no:''})">确认寄出</button>
                      <button v-if="o.shipment_status==='shipped' && o.signoff_status==='pending'" class="secondary xs"
                              @click="act(`/replacement-orders/${o.id}/sign`,{signer:'客户经办人'})">客户签收</button>
                    </td>
                  </tr>
                  <tr v-if="!d.replacement_orders.length"><td colspan="4" class="small muted">
                    尚无替换件出库单；先换路径请先收押金并到「备件指派」批准方案。</td></tr>
                </tbody>
              </table>
              <div v-if="d.path==='inspect_first' && !d.closed" class="row" style="margin-top:10px">
                <input v-model="exchangeSerial" placeholder="复检后换货：已放行兼容备件序列号，如 SP-801" style="flex:1" />
                <button @click="autoAssign">精确指派并原子批准</button>
              </div>
            </div>

            <!-- 旧件回收 -->
            <div class="panel">
              <h2>↩️ 旧件回收（③ 未实收不能成为返修库存）</h2>
              <template v-if="d.old_part_return">
                <div class="row wrap">
                  <span class="mono">{{ d.old_part_return.whole_serial }}</span>
                  <span class="tag" :class="asTagClass(d.old_part_return.status)">{{ RETURN_STATUS[d.old_part_return.status] }}</span>
                  <span v-if="d.old_part_return.overdue" class="tag red">已逾期（应于 {{ fmt(d.old_part_return.due_at) }} 前）</span>
                  <span class="tag gray" v-if="d.old_part_return.disposition!=='pending'">
                    {{ DISPOSITION[d.old_part_return.disposition] }}</span>
                </div>
                <div class="small muted" style="margin:6px 0">{{ d.old_part_return.disposition_note }}</div>
                <div class="row wrap" v-if="!d.closed">
                  <button class="ghost xs" @click="act(`/cases/${no}/old-part/send`,{tracking_no:''})">客户交寄</button>
                  <button class="secondary xs" @click="act(`/cases/${no}/old-part/receive`,{tracking_no:''})">仓库实收</button>
                  <button class="ghost xs" @click="act(`/cases/${no}/old-part/to-rework-stock`,{})">入返修库存</button>
                  <button class="ghost xs" @click="act(`/cases/${no}/old-part/scrap`,{note:'检测后报废'})">报废</button>
                  <button class="ghost xs" @click="act(`/cases/${no}/old-part/return-customer`,{note:'无故障原机退回'})">原机退回客户</button>
                </div>
              </template>
            </div>

            <!-- 返修检测 -->
            <div class="panel">
              <h2>🔬 返修检测（④ 独立状态）</h2>
              <template v-if="d.inspection">
                <span class="tag" :class="asTagClass(d.inspection.status)">{{ INSP_STATUS[d.inspection.status] }}</span>
                <span class="tag gray" v-if="d.inspection.result">{{ INSP_RESULT[d.inspection.result] }}</span>
                <p class="small">{{ d.inspection.report }}</p>
                <div v-if="d.inspection.status!=='concluded' && !d.closed">
                  <div class="grid cols-2">
                    <select v-model="insp.result">
                      <option value="terminal_repairable">可仅修端子</option>
                      <option value="repairable">可维修</option>
                      <option value="fault_confirmed">故障成立/换货</option>
                      <option value="no_fault">无故障</option>
                      <option value="scrap">报废</option>
                    </select>
                    <select v-model="insp.liability">
                      <option value="undetermined">责任待定</option>
                      <option value="supplier">供应商责任</option>
                      <option value="transport">运输责任</option>
                      <option value="customer">客户责任</option>
                      <option value="shared">分担责任</option>
                    </select>
                  </div>
                  <textarea v-model="insp.report" placeholder="检测报告（必填，备注不能替代）" style="margin-top:8px"></textarea>
                  <div class="row end" style="margin-top:8px">
                    <button class="ghost" @click="act(`/cases/${no}/inspection/start`,{})">开始检测</button>
                    <button @click="concludeInspection">出具检测结论</button>
                  </div>
                </div>
                <button v-else-if="!d.closed" class="ghost" @click="act(`/cases/${no}/inspection/start`,{})">开始/继续检测</button>
              </template>
            </div>

            <!-- 维修记录 -->
            <div class="panel">
              <h2>🔧 真实维修与去向（端子维修防整机重复换出）</h2>
              <div v-for="r in d.repairs" :key="r.id" class="repair-line">
                <b>{{ r.repair_kind === 'terminal_only' ? '只修端子' : r.repair_kind }}</b>
                <div class="small">真实部件：{{ r.actual_component_name }}
                  <span class="mono muted">{{ r.actual_component_serial }} ×{{ r.quantity }}</span></div>
                <div class="small">旧部件去向：{{ r.old_component_disposition }}</div>
                <div class="small">整机/旧件去向：{{ r.whole_unit_whereabouts }}</div>
              </div>
              <div class="grid cols-2" v-if="!d.closed" style="margin-top:8px">
                <input v-model="repair.actual_component_name" placeholder="真实部件名称，如 主功率端子 TB-75A" />
                <input v-model="repair.actual_component_serial" placeholder="真实部件批次/序列号" />
                <input type="number" v-model.number="repair.quantity" placeholder="数量" />
                <input v-model="repair.old_component_disposition" placeholder="旧部件去向（如 破坏性报废）" />
                <input v-model="repair.whole_unit_whereabouts" placeholder="整机/旧件实际去向（必填）" style="grid-column:1/3" />
              </div>
              <div class="row end" style="margin-top:8px" v-if="!d.closed">
                <button class="secondary" @click="recordRepair">登记端子维修并锁死整机序列号</button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref, watch } from 'vue'
import { api } from '../api'
import {
  AS_CASE_STATUS, AS_PATH, DEPOSIT_STATUS, LIABILITY, SHIP_STATUS, SIGN_STATUS,
  RETURN_STATUS, INSP_STATUS, INSP_RESULT, DISPOSITION, asTagClass,
} from '../statusLabels'

const PARTY = { customer: '客户保管', logistics: '物流在途', warehouse: '售后仓保管', lab: '检测/工程区保管' }
const CHANNEL = { phone: '电话', im: '即时消息', onsite: '现场', letter: '函件', note: '备注' }

const cases = ref([])
const d = ref(null)
const no = ref('AS-O31')
const msg = ref('')
const err = ref('')

const checkDraft = reactive({})
const liab = reactive({ liability: 'supplier', rationale: '' })
const newCheck = reactive({ title: '' })
const contact = reactive({ channel: 'phone', note: '', next: '' })
const sched = reactive({ commitment: '', commitment_note: '', next: '', next_note: '' })
const custody = reactive({ party: 'warehouse', name: '售后仓', note: '' })
const depositAmount = ref(3000)
const payResolution = ref('released')
const exchangeSerial = ref('')
const insp = reactive({ result: 'terminal_repairable', liability: 'supplier', report: '' })
const repair = reactive({
  actual_component_name: '', actual_component_serial: '', quantity: 1,
  old_component_disposition: '', whole_unit_whereabouts: '',
})

function fmt(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('zh-CN', { hour12: false })
}

async function loadCases() {
  cases.value = await api.get('/api/aftersales/cases')
}
async function loadDetail() {
  d.value = await api.get(`/api/aftersales/cases/${no.value}`)
  for (const c of d.value.engineering_checks) {
    if (!checkDraft[c.id]) checkDraft[c.id] = reactive({ result: 'ruled_out', conclusion: '' })
  }
  sched.commitment = dtLocal(d.value.commitment_deadline)
  sched.commitment_note = d.value.commitment_note || ''
  sched.next = dtLocal(d.value.next_contact && d.value.next_contact.at)
  sched.next_note = d.value.next_contact.note || ''
}
function dtLocal(iso) {
  if (!iso) return ''
  const x = new Date(iso)
  const p = (n) => String(n).padStart(2, '0')
  return `${x.getFullYear()}-${p(x.getMonth() + 1)}-${p(x.getDate())}T${p(x.getHours())}:${p(x.getMinutes())}`
}
async function loadAll() {
  await loadCases()
  await loadDetail()
}
async function selectCase(n) {
  no.value = n
  msg.value = ''
  err.value = ''
  await loadDetail()
}

async function act(url, body = {}, okText = '操作成功') {
  msg.value = ''
  err.value = ''
  try {
    const r = await api.post(`/api/aftersales${url}`, body)
    msg.value = okText
    await loadAll()
    return r
  } catch (e) {
    err.value = e.message
    if (e.details && e.details.blockers) {
      err.value += '：' + e.details.blockers.map((b) => b.message).join('；')
    }
    return null
  }
}

async function concludeCheck(id) {
  const draft = checkDraft[id]
  if (!draft.conclusion.trim()) { err.value = '必须填写补核结论，备注不能替代结论'; return }
  await act(`/engineering-checks/${id}/conclude`, { ...draft }, '工程补核结论已记录')
}
async function addCheck() {
  if (!newCheck.title.trim()) return
  await act(`/cases/${no.value}/engineering-checks`, { kind: 'other', title: newCheck.title })
  newCheck.title = ''
}
async function decideLiability() {
  if (!liab.rationale.trim()) { err.value = '请填写责任依据'; return }
  await act(`/cases/${no.value}/liability`, { ...liab }, '责任结论已出具')
}
async function addContact() {
  if (!contact.note.trim()) { err.value = '请填写沟通内容'; return }
  await act(`/cases/${no.value}/contact`, {
    channel: contact.channel, note: contact.note,
    next_contact_at: contact.next ? new Date(contact.next).toISOString() : null,
  }, '联系已记录')
  contact.note = ''; contact.next = ''
}
async function saveSchedule() {
  await act(`/cases/${no.value}/schedule`, {
    commitment_deadline: sched.commitment ? new Date(sched.commitment).toISOString() : null,
    commitment_note: sched.commitment_note,
    next_contact_at: sched.next ? new Date(sched.next).toISOString() : null,
    next_contact_note: sched.next_note,
  }, '日程/承诺已保存')
}
async function transferCustody() {
  if (!custody.name.trim()) { err.value = '请填写保管人名称'; return }
  await act(`/cases/${no.value}/custody`, { ...custody }, '保管人已转移并留痕')
}
async function concludeInspection() {
  if (!insp.report.trim()) { err.value = '请填写检测报告'; return }
  await act(`/cases/${no.value}/inspection/conclude`, { ...insp }, '检测结论已记录')
}
async function recordRepair() {
  if (!repair.actual_component_name.trim() || !repair.whole_unit_whereabouts.trim()) {
    err.value = '真实部件名称与整机去向为必填'; return
  }
  await act(`/cases/${no.value}/repairs`, { ...repair }, '维修已记录，整机序列号已禁止重复换出')
}
async function autoAssign() {
  if (!exchangeSerial.value.trim()) { err.value = '请填写兼容备件序列号'; return }
  const r = await act(`/cases/${no.value}/exchange/auto-assign`,
    { supply_serial: exchangeSerial.value.trim(), cost: 1 }, '复检后换货已指派并原子批准出库')
  if (r) exchangeSerial.value = ''
}
async function closeCase() {
  await act(`/cases/${no.value}/close`, { note: '实物与资金两清' }, '案件已结案')
}
async function withdraw() {
  if (!window.confirm('确认撤案？已寄出的替换件不会恢复为可用库存。')) return
  await act(`/cases/${no.value}/withdraw`, {}, '案件已撤案')
}
async function resetDemo() {
  if (!window.confirm('将清空并重建售后演示数据，确认？')) return
  msg.value = ''; err.value = ''
  try {
    await api.post('/api/aftersales/demo/reset', {})
    msg.value = '售后演示数据已重置'
    await loadAll()
  } catch (e) { err.value = e.message }
}

watch(no, () => { err.value = ''; msg.value = '' })
onMounted(loadAll)
</script>

<style scoped>
.demo-strip { border-left: 4px solid var(--primary); }
.demo-cards { display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; }
.demo-card {
  border: 1px solid var(--border); border-radius: 8px; padding: 10px; cursor: pointer;
  display: flex; flex-direction: column; gap: 6px; font-size: 12.5px; background: #fafcff;
}
.demo-card:hover { border-color: var(--primary); background: var(--tag-bg); }
.demo-card span { color: var(--muted); line-height: 1.5; }
.as-layout { display: grid; grid-template-columns: 330px 1fr; gap: 16px; align-items: start; }
.case-list { position: sticky; top: 12px; max-height: calc(100vh - 24px); overflow: auto; }
.case-item { border: 1px solid var(--border); border-radius: 8px; padding: 9px 11px; margin-bottom: 8px; cursor: pointer; }
.case-item:hover { border-color: var(--primary); }
.case-item.active { border-color: var(--primary); background: var(--tag-bg); box-shadow: inset 3px 0 0 var(--primary); }
.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; align-items: start; }
.two-col .panel { margin-bottom: 16px; }
.kpi4 { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-top: 12px; }
.kpi { background: #f8fafc; border: 1px solid var(--border); border-radius: 8px; padding: 9px 11px; min-width: 0; }
.kpi label { margin-bottom: 3px; }
.kpi-v { font-weight: 700; font-size: 14px; }
.kpi-v.warn { color: var(--warn); }
.kpi-v.danger { color: var(--danger); }
.preserved {
  background: #f8fafc; border: 1px dashed var(--border); border-radius: 7px;
  padding: 8px 10px; font-size: 12.5px; line-height: 1.7; white-space: pre-wrap;
}
.check-row { border-top: 1px solid var(--border); padding: 9px 0; }
.custody-line { line-height: 1.7; display: flex; gap: 6px; flex-wrap: wrap; }
.repair-line { border-left: 3px solid var(--ok); background: #f6fef9; padding: 7px 10px; border-radius: 0 7px 7px 0; margin-bottom: 8px; line-height: 1.7; }
.msg.warn-inline { background: #fffaeb; color: var(--warn); border: 1px solid #fedf89; padding: 9px 12px; border-radius: 8px; font-size: 13px; margin-top: 8px; }
.closed-panel { border-color: #abefc6; }
button.xs { padding: 4px 9px; font-size: 12px; }
.row.between { justify-content: space-between; }
.row.wrap { flex-wrap: wrap; }
hr { border: none; border-top: 1px solid var(--border); margin: 12px 0; }
.danger { color: var(--danger); }
button.ghost.danger { color: var(--danger); border-color: #fda29b; background: #fff; }
@media (max-width: 1200px) { .demo-cards { grid-template-columns: repeat(2,1fr); } .two-col { grid-template-columns: 1fr; } }
@media (max-width: 900px) { .as-layout { grid-template-columns: 1fr; } .kpi4 { grid-template-columns: repeat(2,1fr); } }
</style>
