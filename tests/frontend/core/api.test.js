import { API_BASE, apiBlob, apiGet, apiPost, downloadBlob, extractErrorMessage, query } from '../../../src/core/api'

function okResponse(data) {
    return {
        ok: true,
        json: () => Promise.resolve(data),
        blob: () => Promise.resolve(data),
        text: () => Promise.resolve(JSON.stringify(data))
    }
}

afterEach(() => {
    delete global.fetch
})

describe('core/api', () => {
    it('registers every endpoint under the plugin id', () => {
        expect(API_BASE).toBe('/machine/MeltingplotConfig')
    })

    describe('extractErrorMessage', () => {
        it('prefers the daemon\'s error field', async () => {
            const response = { text: () => Promise.resolve('{"error":"repo missing"}'), statusText: 'Bad Request' }
            await expect(extractErrorMessage(response)).resolves.toBe('repo missing')
        })

        it('falls back to the raw body when it is not JSON', async () => {
            const response = { text: () => Promise.resolve('plain failure'), statusText: 'Bad Request' }
            await expect(extractErrorMessage(response)).resolves.toBe('Bad Request')
        })

        it('falls back to the status text when the body cannot be read', async () => {
            const response = { statusText: 'Not Found' }
            await expect(extractErrorMessage(response)).resolves.toBe('Not Found')
        })
    })

    describe('apiGet', () => {
        it('prefixes the path and parses JSON', async () => {
            global.fetch = jest.fn(() => Promise.resolve(okResponse({ status: 'ok' })))
            await expect(apiGet('/status')).resolves.toEqual({ status: 'ok' })
            expect(global.fetch).toHaveBeenCalledWith('/machine/MeltingplotConfig/status')
        })

        it('rejects with the daemon error message', async () => {
            global.fetch = jest.fn(() => Promise.resolve({
                ok: false,
                statusText: 'Bad Request',
                text: () => Promise.resolve('{"error":"no reference repo"}')
            }))
            await expect(apiGet('/diff')).rejects.toThrow('no reference repo')
        })
    })

    describe('apiPost', () => {
        it('sends an empty POST without a body', async () => {
            global.fetch = jest.fn(() => Promise.resolve(okResponse({})))
            await apiPost('/sync')
            expect(global.fetch).toHaveBeenCalledWith(
                '/machine/MeltingplotConfig/sync', { method: 'POST' }
            )
        })

        it('sends a JSON body when one is given', async () => {
            global.fetch = jest.fn(() => Promise.resolve(okResponse({})))
            await apiPost('/applyHunks?file=a', { hunks: [0, 2] })
            const [, options] = global.fetch.mock.calls[0]
            expect(options.headers).toEqual({ 'Content-Type': 'application/json' })
            expect(JSON.parse(options.body)).toEqual({ hunks: [0, 2] })
        })

        it('rejects on a failed response', async () => {
            global.fetch = jest.fn(() => Promise.resolve({
                ok: false, statusText: 'Internal Error', text: () => Promise.resolve('')
            }))
            await expect(apiPost('/apply')).rejects.toThrow('Internal Error')
        })
    })

    describe('apiBlob', () => {
        it('returns the raw body', async () => {
            const blob = new Blob(['zip'])
            global.fetch = jest.fn(() => Promise.resolve({ ok: true, blob: () => Promise.resolve(blob) }))
            await expect(apiBlob('/backupDownload?hash=abc')).resolves.toBe(blob)
        })

        it('rejects on a failed response', async () => {
            global.fetch = jest.fn(() => Promise.resolve({ ok: false, statusText: 'Not Found' }))
            await expect(apiBlob('/backupDownload?hash=abc')).rejects.toThrow('Not Found')
        })
    })

    describe('query', () => {
        it('encodes keys and values', () => {
            expect(query({ file: 'sys/config.g' })).toBe('file=sys%2Fconfig.g')
            expect(query({ hash: 'abc', file: 'a b' })).toBe('hash=abc&file=a%20b')
        })
    })

    describe('downloadBlob', () => {
        it('clicks a temporary anchor and revokes the object URL', () => {
            const click = jest.fn()
            const anchor = { click, href: '', download: '' }
            jest.spyOn(document, 'createElement').mockReturnValue(anchor)
            jest.spyOn(document.body, 'appendChild').mockImplementation(() => {})
            jest.spyOn(document.body, 'removeChild').mockImplementation(() => {})
            URL.createObjectURL = jest.fn(() => 'blob:mock')
            URL.revokeObjectURL = jest.fn()

            downloadBlob(new Blob(['x']), 'backup-abc.zip')

            expect(anchor.href).toBe('blob:mock')
            expect(anchor.download).toBe('backup-abc.zip')
            expect(click).toHaveBeenCalled()
            expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:mock')

            document.createElement.mockRestore()
            document.body.appendChild.mockRestore()
            document.body.removeChild.mockRestore()
        })
    })
})
