# Despliegue de NutriGuide en UM Cloud (Kubernetes)

Secuencia completa, en orden. Cada paso dice dónde se corre.

Estado previo ya resuelto: proyecto `tomaslicciardi-project` y namespace
`tomaslicciardi-dev` creados en `cluster-01`; `kubectl` configurado en la VM
`nutriguide-kube` (10.201.2.138).

---

## 1. Publicar las imágenes — en tu PC

Las imágenes ya están construidas localmente:

```
docker.io/tomaslicciardi/nutriguide-backend:v1
docker.io/tomaslicciardi/nutriguide-admin:v1
```

Falta subirlas a Docker Hub. Una sola vez, loguearse (pide usuario y
contraseña de hub.docker.com; crear la cuenta si no existe):

```powershell
docker login
```

Después:

```powershell
docker push docker.io/tomaslicciardi/nutriguide-backend:v1
docker push docker.io/tomaslicciardi/nutriguide-admin:v1
```

La del backend pesa ~1,5 GB (lleva MarianMT adentro). Tarda.

Si el nombre de usuario de Docker Hub no es `tomaslicciardi`, hay que
re-taggear y corregir `03-statefulset.yaml`:

```powershell
docker tag docker.io/tomaslicciardi/nutriguide-backend:v1 docker.io/TU_USUARIO/nutriguide-backend:v1
```

---

## 2. Llevar los manifiestos a la VM — en tu PC

```powershell
scp -i "C:\Users\Usuario\Desktop\Claves\Tomas Licciardi Claves.pem" -r k8s ubuntu@10.201.2.138:~/nutriguide-k8s
```

---

## 3. Secrets — en la VM

Nunca van en un YAML. Se crean directo con `kubectl`. Reemplazar la API key
por la real (la que está en `backend/.env`):

```bash
cd ~/nutriguide-k8s
kubectl -n tomaslicciardi-dev create secret generic nutriguide-secrets \
  --from-literal=JWT_SECRET_KEY="$(python3 -c 'import secrets;print(secrets.token_urlsafe(48))')" \
  --from-literal=SESSION_SECRET="$(python3 -c 'import secrets;print(secrets.token_urlsafe(48))')" \
  --from-literal=GEMINI_API_KEY="AQ.Ab8RN6...PEGAR-LA-KEY-COMPLETA"
```

Comprobar: `kubectl -n tomaslicciardi-dev get secret nutriguide-secrets`

---

## 4. Aplicar en orden — en la VM

```bash
kubectl apply -f 02-configmap.yaml
kubectl apply -f 03-statefulset.yaml
kubectl apply -f 04-services.yaml
kubectl apply -f 05-ingress.yaml
```

`00-namespace.yaml` no se aplica: el namespace ya existe y lo creó
`kube-create-ns.sh` con los permisos correctos.

Seguir el arranque:

```bash
kubectl -n tomaslicciardi-dev get pods -w
```

El pod `nutriguide-0` tarda **1–2 minutos** en pasar a `2/2 Running`: el
backend carga MarianMT y las taxonomías. Si queda en `Pending`, mirar
`kubectl -n tomaslicciardi-dev describe pod nutriguide-0` — casi siempre es
el PVC (storageClass) o un ResourceQuota del namespace.

Si queda en `ContainerCreating` con `FailedMount ... apparently in use by
the system; will not make a filesystem here!`, Longhorn no puede formatear
el volumen en ese worker (pasó el 13/11/2026 en `cluster-01-workers2-kcnjb-c4wsf`).
El StatefulSet ya excluye ese nodo con `nodeAffinity`; si aparece en otro,
agregarlo a la lista y recrear el volumen:

```bash
kubectl -n tomaslicciardi-dev scale statefulset nutriguide --replicas=0
kubectl -n tomaslicciardi-dev delete pod nutriguide-0 --grace-period=0 --force --ignore-not-found
kubectl -n tomaslicciardi-dev delete pvc data-nutriguide-0
# editar 03-statefulset.yaml (values: [...]) y
kubectl apply -f 03-statefulset.yaml && kubectl -n tomaslicciardi-dev scale statefulset nutriguide --replicas=1
```

**Llevar la base local al cluster** (los ingredientes aprendidos hacen la
demo más rápida; sin esto arranca con la semilla). Desde la PC:

```powershell
cd backend
python -c "import sqlite3;s=sqlite3.connect('nutriguide.db');d=sqlite3.connect('snap.db');s.backup(d);d.close()"
scp -O -i "C:\Users\Usuario\Desktop\Claves\Tomas Licciardi Claves.pem" snap.db ubuntu@10.201.2.138:~/snap.db
```

En la VM:

```bash
kubectl -n tomaslicciardi-dev cp ~/snap.db nutriguide-0:/app/db/nutriguide.db.new -c backend
kubectl -n tomaslicciardi-dev exec nutriguide-0 -c backend -- mv /app/db/nutriguide.db.new /app/db/nutriguide.db
kubectl -n tomaslicciardi-dev delete pod nutriguide-0     # reinicia y toma la base nueva
```

---

## 5. Verificar — desde cualquier lado con ZeroTier

```bash
curl https://tomaslicciardi-api.my.kube.um.edu.ar/health
```

Si el Ingress no resuelve, Plan B por NodePort:

```bash
kubectl apply -f 06-nodeport-plan-b.yaml
kubectl get nodes -o wide     # tomar la IP interna de cualquier worker
curl http://IP_DEL_NODO:30080/health
```

---

## 6. Crear el usuario admin del panel — en la VM

```bash
kubectl -n tomaslicciardi-dev exec -it nutriguide-0 -c backend -- \
  python scripts/create_admin.py --email admin@nutriguide.local --password ELEGIR-UNA
```

Panel: `https://tomaslicciardi-admin.my.kube.um.edu.ar`

---

## 7. Apuntar la app — en el celular

Instalar `NutriGuide.apk` (está en la raíz del proyecto). En el login,
tocar el engranaje y poner:

```
https://tomaslicciardi-api.my.kube.um.edu.ar
```

Con **https**: el ingress del cluster redirige todo HTTP a HTTPS (308) y el
certificado es un wildcard de Let's Encrypt (`*.my.kube.um.edu.ar`, vence
23/01/2027), así que Android lo acepta sin configurar nada.

**Límite de 1 MB por request en el borde de UM Cloud.** El proxy que está
delante del ingress-nginx devuelve `413 Request Entity Too Large` con fotos
de más de ~1 MB; directo al ingress-nginx (anotación `proxy-body-size: 20m`)
pasan. No se puede cambiar desde el namespace. La app comprime a 1200 px y
calidad 85 antes de subir (`ImageOptimizer.kt`, 120–250 KB), así que no
afecta al celular; sí afecta a pruebas con `curl` y fotos originales.

**Validado el 13/11/2026 desde la PC con ZeroTier:** las 6 imágenes de
`demo_final/` por la URL pública, 6/6 veredictos correctos, 2,5–5,9 s de
punta a punta (2,3–5,0 s de procesamiento en el pod).

El celular tiene que tener **ZeroTier** conectado a la red de UM Cloud, o
estar en la red de la universidad. Sin eso, ese host no resuelve.

Para probar en casa sin Kubernetes: backend corriendo en la PC con
`--host 0.0.0.0` y en la app poner `http://IP-DE-LA-PC:8000` (misma WiFi).

---

## Actualizar después de un cambio de código

```powershell
docker build -t docker.io/tomaslicciardi/nutriguide-backend:v2 ./backend
docker push docker.io/tomaslicciardi/nutriguide-backend:v2
```

En la VM, cambiar `v1` por `v2` en `03-statefulset.yaml` y
`kubectl apply -f 03-statefulset.yaml`. El StatefulSet baja el pod viejo
antes de subir el nuevo (un solo escritor sobre SQLite, siempre).

---

## Por qué está hecho así

- **StatefulSet, no Deployment:** garantiza que nunca haya dos pods
  escribiendo el mismo archivo SQLite. Un Deployment arranca el nuevo antes
  de matar el viejo.
- **Backend y admin en el mismo pod:** comparten el archivo de la base por
  un volumen `ReadWriteOnce`, que no se puede montar en dos pods. Si se
  migra a PostgreSQL, se separan en dos Deployments.
- **MarianMT dentro de la imagen:** evita 300 MB de descarga en cada
  arranque y que el readiness probe falle por timeout.

---

## Si `kubectl` dice `system:unauthenticated`

El kubeconfig que genera Rancher vence a los **30 días**, aunque el token de
API siga vigente. Regenerarlo desde la VM, sin pasar por la web:

```bash
rancher kubectl config view --raw > ~/.kube/config.new && install -m 600 ~/.kube/config.new ~/.kube/config
kubectl config set-context --current --namespace=tomaslicciardi-dev
```

El token de API (`token-m6dpk`) vence el **14/12/2026**; después de esa fecha
hay que crear una API key nueva en Rancher y repetir `kube-setup.sh`.
Detalle completo en `PLAN_CONTINGENCIA.md` (raíz del proyecto).
