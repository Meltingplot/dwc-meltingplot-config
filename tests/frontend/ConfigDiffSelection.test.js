import { shallowMount, mount } from '@vue/test-utils'
import Vuetify from 'vuetify'
import ConfigDiff from '../../src/components/ConfigDiff.vue'

function detailHunks(count, selected = true) {
  return Array.from({ length: count }, (_, i) => ({
    index: i,
    header: `@@ -${i + 1},1 +${i + 1},1 @@`,
    lines: [`-old${i}`, `+new${i}`],
    selected
  }))
}

function mountComponent(files = []) {
  return shallowMount(ConfigDiff, {
    vuetify: global.createVuetify(),
    propsData: { files }
  })
}

describe('ConfigDiff — partial apply selection', () => {
  describe('default state', () => {
    it('marks every changed file as selected', () => {
      const files = [
        { file: 'sys/config.g', status: 'modified', hunks: [] },
        { file: 'sys/homeall.g', status: 'missing', hunks: [] }
      ]
      mountComponent(files)
      expect(files[0].selected).toBe(true)
      expect(files[1].selected).toBe(true)
    })

    it('keeps the button labelled "Apply All" and emits apply-all', () => {
      const wrapper = mountComponent([
        { file: 'sys/config.g', status: 'modified', hunks: [] }
      ])
      expect(wrapper.vm.isPartialApply).toBe(false)
      expect(wrapper.vm.applyButtonLabel).toBe('Apply All')

      wrapper.vm.emitApply()
      expect(wrapper.emitted('apply-all')).toHaveLength(1)
      expect(wrapper.emitted('apply-selection')).toBeFalsy()
    })

    it('ignores files that were already selected explicitly', () => {
      const files = [{ file: 'sys/config.g', status: 'modified', selected: false }]
      mountComponent(files)
      expect(files[0].selected).toBe(false)
    })
  })

  describe('deselecting a whole file', () => {
    const buildFiles = () => [
      { file: 'sys/config.g', status: 'modified', hunks: [] },
      { file: 'sys/homeall.g', status: 'modified', hunks: [] }
    ]

    it('switches the button to "Partially Apply"', () => {
      const files = buildFiles()
      const wrapper = mountComponent(files)
      wrapper.vm.setFileSelected(files[0], false)

      expect(wrapper.vm.isPartialApply).toBe(true)
      expect(wrapper.vm.applyButtonLabel).toBe('Partially Apply')
      expect(wrapper.vm.selectionState.excludedFiles).toBe(1)
    })

    it('leaves the deselected file out of the payload', () => {
      const files = buildFiles()
      const wrapper = mountComponent(files)
      wrapper.vm.setFileSelected(files[0], false)
      wrapper.vm.emitApply()

      expect(wrapper.emitted('apply-all')).toBeFalsy()
      expect(wrapper.emitted('apply-selection')[0]).toEqual([
        { files: [{ file: 'sys/homeall.g' }], excludedFiles: 1, partialFiles: 0 }
      ])
    })

    it('also clears the hunk checkboxes of that file', () => {
      const files = [
        { file: 'sys/config.g', status: 'modified', hunks: detailHunks(2) }
      ]
      const wrapper = mountComponent(files)
      wrapper.vm.setFileSelected(files[0], false)

      expect(files[0].hunks.every(h => h.selected === false)).toBe(true)
      expect(wrapper.vm.fileChecked(files[0])).toBe(false)
    })

    it('re-selects every hunk when the file is checked again', () => {
      const files = [
        { file: 'sys/config.g', status: 'modified', hunks: detailHunks(3) }
      ]
      const wrapper = mountComponent(files)
      files[0].hunks[1].selected = false
      wrapper.vm.setFileSelected(files[0], false)
      wrapper.vm.setFileSelected(files[0], true)

      expect(files[0].hunks.every(h => h.selected === true)).toBe(true)
      expect(wrapper.vm.isPartialApply).toBe(false)
    })

    it('disables the apply button when nothing is left selected', () => {
      const files = buildFiles()
      const wrapper = mountComponent(files)
      wrapper.vm.deselectAllFiles()

      expect(wrapper.vm.applyDisabled).toBe(true)
      wrapper.vm.emitApply()
      expect(wrapper.emitted('apply-all')).toBeFalsy()
      expect(wrapper.emitted('apply-selection')).toBeFalsy()
    })

    it('selectAllFiles restores the full apply', () => {
      const files = buildFiles()
      const wrapper = mountComponent(files)
      wrapper.vm.deselectAllFiles()
      wrapper.vm.selectAllFiles()

      expect(wrapper.vm.isPartialApply).toBe(false)
      expect(wrapper.vm.selectionState.files).toHaveLength(2)
    })
  })

  describe('deselecting a single hunk', () => {
    const buildFiles = () => [
      { file: 'sys/config.g', status: 'modified', hunks: detailHunks(3) },
      { file: 'sys/homeall.g', status: 'modified', hunks: [] }
    ]

    it('switches the button to "Partially Apply"', () => {
      const files = buildFiles()
      const wrapper = mountComponent(files)
      files[0].hunks[1].selected = false

      expect(wrapper.vm.isPartialApply).toBe(true)
      expect(wrapper.vm.applyButtonLabel).toBe('Partially Apply')
      expect(wrapper.vm.selectionState.partialFiles).toBe(1)
      expect(wrapper.vm.selectionState.excludedFiles).toBe(0)
    })

    it('sends only the kept hunk indices for that file', () => {
      const files = buildFiles()
      const wrapper = mountComponent(files)
      files[0].hunks[1].selected = false
      wrapper.vm.emitApply()

      expect(wrapper.emitted('apply-selection')[0]).toEqual([
        {
          files: [
            { file: 'sys/config.g', hunks: [0, 2] },
            { file: 'sys/homeall.g' }
          ],
          excludedFiles: 0,
          partialFiles: 1
        }
      ])
    })

    it('reports a partly selected file as indeterminate but still checked', () => {
      const files = buildFiles()
      const wrapper = mountComponent(files)
      files[0].hunks[1].selected = false

      expect(wrapper.vm.fileChecked(files[0])).toBe(true)
      expect(wrapper.vm.fileIsPartial(files[0])).toBe(true)
    })

    it('treats a file with every hunk deselected as excluded', () => {
      const files = buildFiles()
      const wrapper = mountComponent(files)
      wrapper.vm.deselectAllHunks(files[0])

      expect(wrapper.vm.fileChecked(files[0])).toBe(false)
      expect(wrapper.vm.fileIsPartial(files[0])).toBe(false)
      expect(wrapper.vm.selectionState.excludedFiles).toBe(1)
      expect(wrapper.vm.selectionState.files).toEqual([{ file: 'sys/homeall.g' }])
    })

    it('sends the whole file when all hunks stay selected', () => {
      const files = buildFiles()
      const wrapper = mountComponent(files)
      wrapper.vm.emitApply()

      expect(wrapper.emitted('apply-all')).toHaveLength(1)
    })
  })

  describe('summary hunks without detail', () => {
    it('are not treated as a hunk selection', () => {
      // diff_all returns { index, header } only — no `lines`, no `selected`
      const files = [
        {
          file: 'sys/config.g',
          status: 'modified',
          hunks: [{ index: 0, header: '@@ -1,1 +1,1 @@' }]
        }
      ]
      const wrapper = mountComponent(files)

      expect(wrapper.vm.hasHunkDetail(files[0])).toBe(false)
      expect(wrapper.vm.fileChecked(files[0])).toBe(true)
      expect(wrapper.vm.fileIsPartial(files[0])).toBe(false)
      expect(wrapper.vm.selectionState.files).toEqual([{ file: 'sys/config.g' }])
    })
  })

  describe('non-applicable files', () => {
    it('excludes "extra" files from the payload without counting them', () => {
      const files = [
        { file: 'sys/config.g', status: 'modified', hunks: [] },
        { file: 'sys/leftover.g', status: 'extra', hunks: [] }
      ]
      const wrapper = mountComponent(files)

      expect(wrapper.vm.selectionState.files).toEqual([{ file: 'sys/config.g' }])
      expect(wrapper.vm.selectionState.excludedFiles).toBe(0)
      expect(wrapper.vm.isPartialApply).toBe(false)
    })

    it('sends "missing" files as whole-file entries', () => {
      const files = [
        { file: 'sys/new.g', status: 'missing', hunks: detailHunks(2) }
      ]
      const wrapper = mountComponent(files)

      expect(wrapper.vm.selectionState.files).toEqual([{ file: 'sys/new.g' }])
      expect(wrapper.vm.fileIsPartial(files[0])).toBe(false)
    })

    it('can still exclude a "missing" file entirely', () => {
      const files = [
        { file: 'sys/new.g', status: 'missing', hunks: detailHunks(2) },
        { file: 'sys/config.g', status: 'modified', hunks: [] }
      ]
      const wrapper = mountComponent(files)
      wrapper.vm.setFileSelected(files[0], false)

      expect(wrapper.vm.selectionState.files).toEqual([{ file: 'sys/config.g' }])
      expect(wrapper.vm.selectionState.excludedFiles).toBe(1)
    })
  })

  describe('reloading the diff', () => {
    it('re-selects everything when a fresh file list arrives', async () => {
      const files = [{ file: 'sys/config.g', status: 'modified', hunks: [] }]
      const wrapper = mountComponent(files)
      wrapper.vm.setFileSelected(files[0], false)
      expect(wrapper.vm.isPartialApply).toBe(true)

      await wrapper.setProps({
        files: [{ file: 'sys/config.g', status: 'modified', hunks: [] }]
      })

      expect(wrapper.vm.isPartialApply).toBe(false)
      expect(wrapper.vm.applyButtonLabel).toBe('Apply All')
    })
  })

  describe('loadFileDetail', () => {
    afterEach(() => {
      delete global.fetch
    })

    it('loads hunks deselected when the file itself is excluded', async () => {
      const wrapper = mountComponent()
      const file = { file: 'sys/config.g', status: 'modified', selected: false }

      global.fetch = jest.fn(() => Promise.resolve({
        ok: true,
        json: () => Promise.resolve({
          hunks: [{ index: 0, header: '@@ -1,1 +1,1 @@', lines: ['-a', '+b'] }]
        })
      }))

      await wrapper.vm.loadFileDetail(file)
      expect(file.hunks[0].selected).toBe(false)
    })
  })

  describe('rendered controls', () => {
    const flush = () => new Promise(r => setTimeout(r, 10))

    function fullMount(files) {
      return mount(ConfigDiff, {
        vuetify: new Vuetify(),
        propsData: { files }
      })
    }

    it('renders one selection checkbox per applicable file', () => {
      const wrapper = fullMount([
        { file: 'sys/config.g', status: 'modified', hunks: [] },
        { file: 'sys/leftover.g', status: 'extra', hunks: [] }
      ])

      const boxes = wrapper.findAll('.v-expansion-panel-header input[type="checkbox"]')
      expect(boxes).toHaveLength(1)
      wrapper.destroy()
    })

    it('unchecking a file does not expand its panel', async () => {
      const files = [{ file: 'sys/config.g', status: 'modified', hunks: [] }]
      const wrapper = fullMount(files)

      const box = wrapper.find('.v-expansion-panel-header input[type="checkbox"]')
      await box.setChecked(false)

      expect(files[0].selected).toBe(false)
      // The click must not bubble to the header, which toggles the panel
      expect(wrapper.vm.expandedPanels).toEqual([])
      wrapper.destroy()
    })

    it('relabels the toolbar button once a file is unchecked', async () => {
      const wrapper = fullMount([
        { file: 'sys/config.g', status: 'modified', hunks: [] },
        { file: 'sys/homeall.g', status: 'modified', hunks: [] }
      ])
      expect(wrapper.text()).toContain('Apply All')

      const box = wrapper.findAll('.v-expansion-panel-header input[type="checkbox"]').at(0)
      await box.setChecked(false)

      expect(wrapper.text()).toContain('Partially Apply')
      expect(wrapper.text()).not.toContain('Apply All')
      expect(wrapper.text()).toContain('1 excluded')
      wrapper.destroy()
    })

    it('disables the toolbar button when every file is unchecked', async () => {
      const wrapper = fullMount([
        { file: 'sys/config.g', status: 'modified', hunks: [] }
      ])
      wrapper.vm.deselectAllFiles()
      await wrapper.vm.$nextTick()

      const applyBtn = wrapper.findAll('.v-btn').wrappers.find(
        b => b.text().includes('Partially Apply')
      )
      expect(applyBtn.attributes('disabled')).toBeTruthy()
      wrapper.destroy()
    })

    it('disables the hunk select/deselect buttons of an excluded file', async () => {
      const files = [
        { file: 'sys/config.g', status: 'modified', hunks: detailHunks(2) }
      ]
      const wrapper = fullMount(files)

      await wrapper.find('.v-expansion-panel-header').trigger('click')
      await flush()

      const hunkToolbarBtn = () => wrapper.findAll('.v-btn').wrappers.find(
        b => b.text().trim() === 'Deselect all'
      )
      expect(hunkToolbarBtn().attributes('disabled')).toBeFalsy()

      wrapper.vm.setFileSelected(files[0], false)
      await flush()

      expect(hunkToolbarBtn().attributes('disabled')).toBeTruthy()
      wrapper.destroy()
    })

    it('disables the hunk checkboxes of an excluded file', async () => {
      const files = [
        { file: 'sys/config.g', status: 'modified', hunks: detailHunks(2) }
      ]
      const wrapper = fullMount(files)

      await wrapper.find('.v-expansion-panel-header').trigger('click')
      await flush()

      const hunkBoxes = wrapper.findAll('.hunk-separator input[type="checkbox"]')
      expect(hunkBoxes.length).toBe(2)
      expect(hunkBoxes.at(0).attributes('disabled')).toBeFalsy()

      wrapper.vm.setFileSelected(files[0], false)
      await flush()

      const disabled = wrapper.findAll('.hunk-separator input[type="checkbox"]')
      expect(disabled.at(0).attributes('disabled')).toBeTruthy()
      wrapper.destroy()
    })
  })
})
