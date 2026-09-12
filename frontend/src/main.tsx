import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter } from 'react-router-dom'
import { isAxiosError } from 'axios'
import './index.css'
import App from './App.tsx'
import { ToastProvider } from '@/components/ui/Toast'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // تحديث 2026-09-12 (بلاغ لاما — بطء ملحوظ بكل الصفحات): كانت `retry: 1`
      // تعيد أي طلب فاشل مرة واحدة بلا استثناء — بما فيها 403 (صلاحية
      // مرفوضة)، اللي أبدًا ما راح تنجح بإعادة المحاولة لأن سبب الرفض
      // (صلاحيات المستخدم) ما يتغيّر خلال نفس الجلسة. كانت تضاعف عدد
      // الطلبات الفعلية لكل استعلام يرجع 403/404/... (مثال: job-titles/
      // roles/permissions/departments بمودالات إضافة مستخدم) — حمل شبكي
      // مضاعف بلا داعٍ يزاحم بقية الطلبات المتزامنة على خادم Render
      // بموارد محدودة (0.1 CPU مشتركة، عامل واحد). الآن: إعادة المحاولة
      // فقط لأخطاء الشبكة/الخادم (5xx أو بلا استجابة)، وليس لأخطاء العميل
      // (4xx) اللي إعادة محاولتها لا تفيد أبدًا.
      retry: (failureCount, error) => {
        if (isAxiosError(error) && error.response && error.response.status < 500) {
          return false
        }
        return failureCount < 1
      },
      staleTime: 30_000,
      refetchOnWindowFocus: false,
    },
  },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <ToastProvider>
          <App />
        </ToastProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
)
