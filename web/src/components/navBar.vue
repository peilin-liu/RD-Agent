<template>
  <div class="header-component">
    <div class="nav">
      <router-link to="/">
        <div class="logo-container">
          <img src="@/assets/images/RDAgent-logo.png" alt="R&D-Agent logo" />
        </div>
      </router-link>
      <ul>
        <li>
          <router-link to="/">Homepage</router-link>
        </li>
        <li>
          <router-link to="/Playground">Playground</router-link>
        </li>
      </ul>
      <div class="region-selector">
        <span class="region-label">Region:</span>
        <el-select v-model="currentRegion" @change="onRegionChange" size="small" placeholder="Select">
          <el-option v-for="r in regionList" :key="r" :label="r.toUpperCase()" :value="r" />
        </el-select>
      </div>
    </div>
  </div>
</template>
<script lang="ts" setup>
import { ref, onMounted } from "vue";
import { getRegions, setRegion } from "@/utils/api";

const regionList = ref<string[]>([]);
const currentRegion = ref("");

onMounted(async () => {
  try {
    const res = await getRegions();
    regionList.value = res.regions || [];
    const saved = sessionStorage.getItem("selectedRegion") || res.default_region || "";
    currentRegion.value = saved;
    sessionStorage.setItem("selectedRegion", saved);
  } catch {}
});

const onRegionChange = async (val: string) => {
  sessionStorage.setItem("selectedRegion", val);
  try {
    await setRegion(val);
  } catch {}
};
</script>
<style scoped lang="scss">
.header-component {
  padding: 1.75em 4.375em 0;
  height: 5.15em;
  box-sizing: border-box;
  & > .nav {
    display: flex;
    flex-wrap: nowrap;
    justify-content: flex-start;
    align-items: center;
    flex-direction: row;
    .logo-container {
      margin-right: 4.375em;
      img {
        display: inline-block;
        height: 2.25em;
      }
    }
    ul {
      display: flex;
      flex-direction: row;
      li {
        margin-right: 2.25em;
        text-align: center;
        cursor: pointer;
        a {
          display: inline-block;
          color: var(--nav-default-color);
          font-size: 1.25em;
          font-weight: 700;
          line-height: 200%;
          &:hover {
            color: var(--nav-hover-color);
          }
        }
        .router-link-exact-active {
          color: var(--text-color);
          &:hover {
            color: var(--text-color);
          }
        }
      }
    }
    .region-selector {
      display: flex;
      align-items: center;
      gap: 0.5em;
      margin-left: auto;
      .region-label {
        font-size: 0.875em;
        color: var(--nav-default-color);
        font-weight: 500;
      }
    }
  }
}
</style>
