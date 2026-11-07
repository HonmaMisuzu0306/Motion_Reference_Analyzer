// Deliberately small AE scripting contract double; not an AE renderer.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
class File {
  constructor(name) { this.fsName = path.resolve(name); }
  get parent() { return new File(path.dirname(this.fsName)); }
  get exists() { return fs.existsSync(this.fsName); }
}
class ImportOptions {
  constructor(file) { this.file = file; }
}
class Property {
  constructor() { this.value = null; this.keys = []; this.followers = {}; }
  get numKeys() { return this.keys.length; }
  setValue(v) { if (this.keys.length) throw Error('setValue on keyed property'); this.value = v; }
  getSeparationFollower(d) {
    if (!this.dimensionsSeparated) throw Error('position not separated');
    return this.followers[d] ||= new Property();
  }
  setValueAtTime(time, value) {
    if (!Number.isFinite(time)) throw Error('invalid time');
    this.keys.push({ time, value });
  }
  setInterpolationTypeAtKey(k, incoming, outgoing) {
    this.keys[k - 1].interpolation = [incoming, outgoing];
  }
}
class Layer {
  constructor(name) { this.name = name; this.props = {}; }
  property(name) {
    if (name !== 'ADBE Transform Group') throw Error('unknown layer group');
    return { property: key => this.props[key] ||= new Property() };
  }
}
const state = { comps: [], folders: [], undoStart: 0, undoEnd: 0, alerts: [] };
const app = {
  beginUndoGroup() { state.undoStart++; }, endUndoGroup() { state.undoEnd++; },
  project: { importFile(options) {
    if (options.sequence !== false || !options.file.exists) throw Error('expected a single existing still');
    return { name: path.basename(options.file.fsName), isImportedStill: true, pixelAspect: .91 };
  }, items: {
    addFolder(name) { const f = { name }; state.folders.push(f); return f; },
    addComp(name, width, height, aspect, duration, fps) {
      if (fps > Number(process.argv[3] || 999)) throw Error('frame rate exceeds host limit');
      const comp = { name, width, height, aspect, duration, fps, entries: [] };
      comp.layers = {
        addNull(duration) {
          const l = new Layer("Null"); Object.assign(l, { nullLayer: true, duration });
          comp.entries.push(l); return l;
        },
        add(source) {
          const l = new Layer(source.name);
          if (source.isImportedStill) { l.sourceName = source.name; l.sourcePixelAspect = source.pixelAspect; }
          comp.entries.push(l); return l;
        },
        addSolid(color, name, w, h, a, d) {
          const l = new Layer(name); Object.assign(l, { color, width: w, height: h, aspect: a, duration: d });
          comp.entries.push(l); return l;
        }
      };
      comp.openInViewer = () => { comp.opened = true; };
      state.comps.push(comp); return comp;
    }
  } }
};
vm.runInNewContext(fs.readFileSync(process.argv[2], 'utf8'), {
  app, File, ImportOptions, $: {fileName: path.resolve(process.argv[2])}, BlendingMode: {NORMAL:'normal', DIFFERENCE:'difference'},
  alert: message => state.alerts.push(message), KeyframeInterpolationType: { LINEAR: 'linear' }
}, { timeout: 1000 });
process.stdout.write(JSON.stringify(state));
