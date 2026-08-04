import { agruparArtefactos } from './resultado-c4';

describe('agruparArtefactos', () => {
  it('groups artifacts from optional type and label metadata', () => {
    const grupos = agruparArtefactos([
      { id: '1', nombre: 'indice.json', tipo: 'semantic_index' },
      { id: '2', nombre: 'evidencia.json', etiqueta: 'Evidencia RAG' },
      { id: '3', nombre: 'juez.json', tipo: 'judge', etiqueta: 'Informe del juez' },
      { id: '4', nombre: 'modelo.dsl' },
    ]);

    expect(grupos.map((grupo) => [grupo.clave, grupo.artefactos.length])).toEqual([
      ['semantica', 1],
      ['rag', 1],
      ['agentes', 1],
      ['c4', 1],
    ]);
  });

  it('keeps artifacts without classification metadata in the C4 group', () => {
    expect(agruparArtefactos([{ id: '1', nombre: 'rag-named-only.json' }])[0].clave).toBe('c4');
  });
});
