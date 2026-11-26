<template>
  <div>
    <div class="panel">
      <h2>🧪 样例 L-7 策略对比仿真</h2>
      <p class="muted small">
        L-7 含四个物理独立的包：P-1 有碰撞记录且未复检；P-2~P-4 身份链完整、检测合格且无共同热事件。
        点击运行后，后端在独立事务中仿真并回滚，<b>不会改变真实业务数据</b>，可重复执行。
      </p>
      <button @click="run" :disabled="loading">{{ loading ? '仿真中…' : '运行 L-7 对比仿真' }}</button>
      <div v-if="error" class="msg err" style="margin-top:12px">{{ error }}</div>
    </div>

    <template v-if="data">
      <div class="grid cols-2">
        <div class="panel">
          <h2>策略一：整批冻结</h2>
          <div class="kv">
            <span class="k">可放行的包</span><span><b class="tag red">{{ bf.releasable.length ? bf.releasable.join('、') : '无（全部挡住）' }}</b></span>
            <span class="k">待拣货单</span><span>{{ bf.picking_count }}</span>
            <span class="k">买家通知</span><span>{{ bf.buyer_notification_count }}</span>
          </div>
          <h3>逐包审批结果</h3>
          <table>
            <tbody>
              <tr v-for="a in bf.approval_attempts" :key="a.pack">
                <td class="mono">{{ a.pack }}</td>
                <td><span class="tag" :class="a.result === 'approved' ? 'green' : 'red'">{{ a.result === 'approved' ? '放行' : '阻止' }}</span></td>
                <td class="small">{{ a.reason || '—' }}</td>
              </tr>
            </tbody>
          </table>
          <p class="small muted">{{ data.conclusion.batch_freeze }}</p>
        </div>

        <div class="panel">
          <h2>策略二：单包隔离</h2>
          <div class="kv">
            <span class="k">初始可放行</span><span><b class="tag green">{{ sp.releasable_at_start.join('、') }}</b></span>
            <span class="k">初始待拣货单</span><span>{{ sp.picking_count_at_start }}</span>
            <span class="k">初始买家通知</span><span>{{ sp.buyer_notification_count_at_start }}</span>
            <span class="k">P-3 浸水后仍流转</span><span class="tag green">{{ sp.after_late_water_p3.still_flowing_packs.join('、') }}</span>
          </div>
          <h3>P-3 出库前收到迟到浸水回执</h3>
          <p class="small">
            拣货尝试：<span class="tag red">{{ sp.after_late_water_p3.p3_pick_attempt.result }}</span>
            {{ sp.after_late_water_p3.p3_pick_attempt.reason }}
          </p>
          <h3>P-1 拆解发现无法匹配的重贴标签</h3>
          <p class="small">
            未知模组 <span class="mono">{{ sp.after_relabel_mismatch_p1.unknown_module.serial_no }}</span>：
            <span class="tag red">隔离待核</span>（pack_id = {{ sp.after_relabel_mismatch_p1.unknown_module.pack_id ?? 'null' }}，未自动归并）
          </p>
          <p class="small">
            工单关闭：<span class="tag red">{{ sp.after_relabel_mismatch_p1.work_order_close_attempt.result }}</span>
            — {{ sp.after_relabel_mismatch_p1.work_order_close_attempt.reason }}
          </p>
          <p class="small muted">{{ data.conclusion.single_pack }}</p>
        </div>
      </div>

      <div class="panel">
        <h2>仿真原始数据（JSON）</h2>
        <pre class="json">{{ JSON.stringify(data, null, 2) }}</pre>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { api } from '../api'

const data = ref(null)
const loading = ref(false)
const error = ref('')
const bf = computed(() => data.value?.batch_freeze_strategy || {})
const sp = computed(() => data.value?.single_pack_strategy || {})

async function run() {
  loading.value = true
  error.value = ''
  try {
    data.value = await api.post('/api/scenario/l7/compare')
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}
</script>
