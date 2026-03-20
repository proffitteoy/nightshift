package com.example.myapplication3.ui.notifications;

import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;

import androidx.annotation.NonNull;
import androidx.fragment.app.Fragment;

import com.example.myapplication3.R;

/**
 * Placeholder fragment after saved-posts functionality was removed.
 */
public class SavedPostsFragment extends Fragment {

    public SavedPostsFragment() {
    }

    @Override
    public View onCreateView(@NonNull LayoutInflater inflater,
                             ViewGroup container, Bundle savedInstanceState) {
        // Avoid project layout reference that may be missing; use system layout placeholder
        View root = inflater.inflate(android.R.layout.simple_list_item_1, container, false);
        android.widget.TextView tv = root.findViewById(android.R.id.text1);
        tv.setText("已移除：保存的帖子页面");
        tv.setGravity(android.view.Gravity.CENTER);
        return root;
    }

}