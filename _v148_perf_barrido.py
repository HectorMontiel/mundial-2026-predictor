import time, warnings, logging, os; warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.ERROR)
import alpha_finder, guardia_barrido as g
g.reiniciar(borrar_disco=True)
t=time.time(); r=g.barrido(alpha_finder.apuestas_del_dia_universal); frio=time.time()-t
print(f'BARRIDO FRIO (sin cache)      : {frio:6.1f} s', flush=True)
print(f'   pronosticos={len(r.get("pronosticos") or [])} elite={len(r.get("elite") or [])} capa2={len(r.get("capa2_futbol") or [])}', flush=True)
t=time.time(); g.barrido(alpha_finder.apuestas_del_dia_universal); print(f'RECARGA (memoria)             : {time.time()-t:6.3f} s', flush=True)
g._estado.update(ts=0.0, datos=None)
t=time.time(); r3=g.barrido(alpha_finder.apuestas_del_dia_universal); disco=time.time()-t
print(f'ARRANQUE DE CONTENEDOR (disco): {disco:6.3f} s   edad={r3["_frescura"]["edad_s"]:.0f}s', flush=True)
print(f'tamano de la cache: {os.path.getsize(".cache_barrido.pkl")/1e6:.2f} MB', flush=True)
print(f'MEJORA: {frio:.0f} s -> {disco:.3f} s', flush=True)
