<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api'

const day = ref('')
const cutoffTime = ref('02:00')
const cutoffPolicy = ref('roll_to_next_day')
const policyLabels = ref({})
const msg = ref('')
const err = ref('')

onMounted(async () => {
  const d = await api.getDay()
  day.value = d.business_day
  const c = await api.getCutoff()
  cutoffTime.value = c.cutoff_time
  cutoffPolicy.value = c.cutoff_policy
  policyLabels.value = c.policy_labels || {}
})

async function saveDay() {
  msg.value = ''; err.value = ''
  try {
    await api.setDay(day.value)
    msg.value = '已更新营业日'
  } catch (e) { err.value = e.message }
}

async function saveCutoff() {
  msg.value = ''; err.value = ''
  try {
    const c = await api.setCutoff({ cutoff_time: cutoffTime.value, cutoff_policy: cutoffPolicy.value })
    cutoffTime.value = c.cutoff_time
    cutoffPolicy.value = c.cutoff_policy
    msg.value = '已更新日内截止配置（仅影响未封日的新流水与封账口径，已封账批次不动）'
  } catch (e) { err.value = e.message }
}
</script>

<template>
  <h2>设置</h2>
  <div class="row">
    <label>营业日 <input v-model="day" placeholder="YYYY-MM-DD" /></label>
    <button class="btn" @click="saveDay">保存</button>
  </div>

  <h3>日内截止归集（全局唯一策略）</h3>
  <div class="panel">
    <div class="row">
      <label>截止时刻（UTC）
        <input type="time" v-model="cutoffTime" />
      </label>
    </div>
    <div class="row">
      <label>归集策略
        <select v-model="cutoffPolicy">
          <option value="roll_to_next_day">{{ policyLabels.roll_to_next_day || '截止后归入次日' }}</option>
          <option value="mark_late">{{ policyLabels.mark_late || '截止后仍归本日并打晚到标' }}</option>
        </select>
      </label>
      <button class="btn" @click="saveCutoff">保存截止配置</button>
    </div>
    <p class="msg">
      严格晚于截止时刻的流水：「归入次日」会落库下一营业日且不进当日封账合计；
      「打晚到标」仍属当日并进入封账合计，批次快照记录晚到笔数与金额。
      修改配置不回溯、不篡改已封账日的批次合计。
    </p>
  </div>

  <p v-if="msg" class="msg">{{ msg }}</p>
  <p v-if="err" class="msg err">{{ err }}</p>
</template>
