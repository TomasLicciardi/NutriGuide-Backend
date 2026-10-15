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

---

## 5. Verificar — desde cualquier lado con ZeroTier

```bash
curl http://tomaslicciardi-api.my.kube.um.edu.ar/health
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

Panel: `http://tomaslicciardi-admin.my.kube.um.edu.ar`

---

## 7. Apuntar la app — en el celular

Instalar `NutriGuide.apk` (está en la raíz del proyecto). En el login,
tocar el engranaje y poner:

```
http://tomaslicciardi-api.my.kube.um.edu.ar
```

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
