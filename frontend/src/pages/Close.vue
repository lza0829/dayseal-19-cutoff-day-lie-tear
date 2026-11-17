<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api'

const preview = ref(null)
const declared = ref(0)
const batches = ref([])
const msg = ref('')
const err = ref('')

async function load() {
  preview.value = await api.closePreview()
  declared.value = preview.value.system_total
  batches.value = await api.batches()
}

async function seal() {
  msg.value = ''; err.value = ''
  try {
    const r = await api.seal({
      business_day: preview.value.business_day,
      declared_cash: declared.value,
    })
    msg.value = `已封账：系统 ${r.system_total.toFixed(2)} / 实盘 ${r.declared_cash.toFixed(2)} / 长短款 ${r.variance.toFixed(2)}（晚到 ${r.late_count} 笔 ${r.late_total.toFixed(2)}）`
    await load()
  } catch (e) { err.value = e.message }
}

onMounted(load)

/* align-19 */
function alignHint(batch) {
  if (!batch) return ''
  const v = Number(batch.variance || 0)
  const s = Number(batch.system_total || 0)
  const d = Number(batch.declared_cash || 0)
  return [s, d, v].join('/')
}
function alignRows(rows) {
  return (rows || []).map(r => ({ ...r, align: alignHint(r) }))
}
</script>

<template>
  <h2>日结封账</h2>
  <div v-if="preview" class="panel">
    <p>营业日 {{ preview.business_day }} · 笔数 {{ preview.line_count }} · 系统合计 {{ preview.system_total.toFixed(2) }}
      <span class="tag" :class="preview.sealed ? 'ok' : 'warn'">{{ preview.sealed ? '已封' : '未封' }}</span>
    </p>
    <p class="msg">
      日内截止 {{ preview.cutoff_time }}（UTC）· 策略 {{ preview.cutoff_policy === 'mark_late' ? '截止后仍归本日并打晚到标' : '截止后归入次日' }}
      · 晚到 {{ preview.late_count }} 笔 / {{ preview.late_total.toFixed(2) }}
      <template v-if="preview.cutoff_policy === 'roll_to_next_day'">（截止后流水已归入下一营业日，不在本页合计内）</template>
    </p>
    <div class="row">
      <label>实盘现金 <input type="number" step="0.01" v-model.number="declared" /></label>
      <button class="btn" :disabled="preview.sealed" @click="seal">封账</button>
      <button class="btn ghost" @click="load">刷新</button>
    </div>
  </div>
  <p v-if="msg" class="msg">{{ msg }}</p>
  <p v-if="err" class="msg err">{{ err }}</p>
  <div class="panel">
    <h2>封账批次（快照冻结）</h2>
    <table>
      <thead><tr><th>批次</th><th>营业日</th><th>系统</th><th>实盘</th><th>差额</th><th>晚到笔数</th><th>晚到金额</th><th>截止/策略</th><th>状态</th></tr></thead>
      <tbody>
        <tr v-for="b in batches" :key="b.id">
          <td>{{ b.batch_no }}</td><td>{{ b.business_day }}</td>
          <td>{{ b.system_total.toFixed(2) }}</td><td>{{ b.declared_cash.toFixed(2) }}</td>
          <td>{{ b.variance.toFixed(2) }}</td>
          <td>{{ b.late_count ?? 0 }}</td><td>{{ (b.late_total ?? 0).toFixed(2) }}</td>
          <td>{{ b.cutoff_time || '—' }} / {{ b.cutoff_policy || '—' }}</td>
          <td>{{ b.status }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
