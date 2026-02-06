import axios from "axios";

const client = axios.create({
  baseURL: "/api/v1",
  timeout: 600_000,
  maxBodyLength: Infinity,
  maxContentLength: Infinity,
});

client.interceptors.response.use(
  (res) => res,
  (error) => {
    const message =
      error.response?.data?.detail ?? error.message ?? "请求失败";
    return Promise.reject(new Error(message));
  },
);

export default client;
