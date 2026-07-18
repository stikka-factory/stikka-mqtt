import { getDocument, GlobalWorkerOptions } from 'pdfjs-dist'

GlobalWorkerOptions.workerSrc = new URL('pdfjs-dist/build/pdf.worker.min.mjs', import.meta.url).toString()

export async function renderPDFPageAsDataURL(file: File): Promise<string> {
  const data = new Uint8Array(await file.arrayBuffer())
  const loadingTask = getDocument({ data })
  const pdf = await loadingTask.promise

  if (pdf.numPages < 1) {
    throw new Error('The PDF has no pages')
  }

  const page = await pdf.getPage(1)
  const baseViewport = page.getViewport({ scale: 1 })
  const maxEdge = 2400
  const edge = Math.max(baseViewport.width, baseViewport.height)
  const scale = edge > maxEdge ? maxEdge / edge : 1.5
  const viewport = page.getViewport({ scale })

  const canvas = document.createElement('canvas')
  canvas.width = Math.ceil(viewport.width)
  canvas.height = Math.ceil(viewport.height)

  const ctx = canvas.getContext('2d')
  if (!ctx) {
    throw new Error('Could not create PDF canvas context')
  }

  await page.render({ canvas, canvasContext: ctx, viewport }).promise
  return canvas.toDataURL('image/png')
}
