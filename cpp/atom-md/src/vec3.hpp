#pragma once

#include <cmath>

// Minimal 3-vector. Kept as a plain aggregate so std::vector<Vec3> is a flat,
// cache-friendly array of 3 doubles per atom.
struct Vec3 {
    double x = 0.0;
    double y = 0.0;
    double z = 0.0;

    Vec3& operator+=(const Vec3& o) { x += o.x; y += o.y; z += o.z; return *this; }
    Vec3& operator-=(const Vec3& o) { x -= o.x; y -= o.y; z -= o.z; return *this; }
    Vec3& operator*=(double s)      { x *= s;   y *= s;   z *= s;   return *this; }
};

inline Vec3 operator+(Vec3 a, const Vec3& b) { return a += b; }
inline Vec3 operator-(Vec3 a, const Vec3& b) { return a -= b; }
inline Vec3 operator*(Vec3 a, double s)      { return a *= s; }
inline Vec3 operator*(double s, Vec3 a)      { return a *= s; }

inline double dot(const Vec3& a, const Vec3& b) {
    return a.x * b.x + a.y * b.y + a.z * b.z;
}

inline double norm2(const Vec3& a) { return dot(a, a); }
inline double norm(const Vec3& a)  { return std::sqrt(norm2(a)); }
