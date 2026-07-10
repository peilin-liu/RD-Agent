import { createRouter, RouteRecordRaw, createWebHashHistory } from 'vue-router'

const routes: Array<RouteRecordRaw> = [
  {
    path: '/',
    name: 'Playground',
    component: () => import('../views/Playground.vue'),
    meta: {
      keepAlive: false,
      requiresFrontEndAuth: true,
      footerBg: "#fff"
    },
  },
  {
    path: '/Home',
    name: 'Home',
    component: () => import('../views/Home.vue'),
    meta: {
      keepAlive: true,
      requiresFrontEndAuth: true,
      footerBg: "#F6FAFF"
    },
  },
  {
    path: '/PlaygroundPage',
    name: 'PlaygroundPage',
    component: () => import('../views/PlaygroundPage.vue'),
    meta: {
      keepAlive: false,
      requiresFrontEndAuth: true,
      footerBg: "#fff"
    },
  }
]

const router = createRouter({
  history: createWebHashHistory(),
  routes
})

// 前端添加密码，防止release流程未走完，外部人员访问
// router.beforeEach((to, from, next) => {
//   console.log(from)
//     if (!!to.meta && to.meta.requiresFrontEndAuth === false) {
//         //这里判断用户是否登录，验证本地存储是否有token
//         next();
//         return;
//     }
//     if (!sessionStorage.getItem("token")) { // 判断当前的token是否存在
//         next({
//             name: 'Login',
//             query: { redirect: to.fullPath }
//         })
//     } else {
//         next();
//     }
// })

export default router